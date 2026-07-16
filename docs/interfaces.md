# Planned Interfaces

This document is the implementation specification for the next Friction
interface milestone. It is intentionally prescriptive: an implementation agent
should be able to complete the milestone without making product or architecture
decisions that are not recorded here.

The milestone adds three interfaces, in this order:

1. a full terminal user interface;
2. an Emacs minor mode for capture only;
3. a local MCP server using only the stdio transport.

This document describes planned behavior. None of these interfaces is part of
the current v1 release until its corresponding acceptance criteria are met.

## Fixed Decisions

- All implementation lives in this repository.
- The TUI is built with Textual and is launched with `friction tui` or `fr tui`.
- The TUI provides complete single-item management. It does not provide
  multi-selection or bulk actions in this milestone.
- The Emacs integration only captures new items. It does not list, search,
  edit, open, or change the status of existing items.
- The Emacs integration is a buffer-local minor mode with an optional globalized
  variant. It calls the JSON CLI asynchronously and never opens SQLite.
- The MCP server is local-only and stdio-only. It provides resources, a prompt,
  read tools, and mutation tools. It has no HTTP listener, authentication, or
  background daemon.
- TUI and MCP call `FrictionService` directly. They must not spawn the CLI or
  issue SQL.
- The existing domain lifecycle, event history, database resolution, and
  optimistic-concurrency rules remain authoritative.
- The existing JSON contract remains schema version 1. This milestone must not
  introduce a schema version 2.
- Neovim, FastAPI, browser UI, Streamable HTTP MCP, remote access, sync, and
  notifications are out of scope.
- The external `configs` repository is not modified. This repository includes
  installation and cutover examples for it.

## User Outcomes

After the milestone, a user can:

- run `friction tui` and manage the complete lifecycle of local items without
  remembering CLI subcommands;
- enable `friction-mode` in Emacs and capture the current buffer context with a
  single command;
- configure an MCP host to launch `friction mcp` and let an agent inspect or
  mutate the same local database;
- observe a write made by any interface in the others without restarting them;
- receive a clear revision-conflict error instead of silently overwriting a
  change made by another interface.

## Architecture and Dependency Direction

The target dependency graph is:

```text
Textual TUI ───────────────┐
MCP stdio server ─────────┼──> FrictionService ──> repository port
Python callers ───────────┘                           |
                                                      v
Emacs minor mode ──> CLI JSON v1              SQLAlchemy / SQLite
```

The domain and application packages must not import Textual, the MCP SDK,
Typer, Emacs-specific code, SQLAlchemy, or Alembic. Interface code converts
interface inputs to the existing domain commands and calls the public service.
Storage remains behind the repository protocol.

Add these runtime dependencies to the normal project dependency set, not to
optional extras:

```toml
"textual>=8.2,<9"
"mcp>=1.28,<2"
```

The MCP upper bound is deliberate. At the time this decision was recorded,
MCP Python SDK 1.x was the stable production line and 2.x was a prerelease with
breaking API changes. Do not adopt MCP SDK 2.x as part of this milestone.

The ordinary installation must include every interface:

```shell
uv tool install .
friction tui
friction mcp
```

The supported platform remains macOS with Python 3.12 or newer. Emacs support
starts at Emacs 29.1.

## Shared Adapter Rules

### Database selection

Both new Python interfaces use the same precedence as the CLI:

1. root `--db PATH` option;
2. `FRICTION_DB_PATH`;
3. `~/Library/Application Support/friction/friction.db`.

The commands are therefore:

```shell
friction tui
friction --db /tmp/friction.db tui
friction mcp
friction --db /tmp/friction.db mcp
```

Both commands apply packaged Alembic migrations before starting their event
loop. Migration failure is fatal and must be reported without starting a
partially working interface.

### Source attribution

Do not add `tui` to `ItemSource` because that would expand an enum in the stable
JSON v1 contract. Attribution is fixed as follows:

- TUI captures use `source="cli"` and force `metadata.interface="tui"`;
- Emacs captures use `source="emacs"`;
- MCP captures use `source="mcp"`;
- edits and lifecycle operations never change the original source.

When the TUI add form contains user metadata, `metadata.interface` is reserved
and overwritten with `"tui"`. Editing an existing item preserves its metadata
unless the user explicitly changes it. An existing non-TUI item is not marked
as TUI-originated merely because it was edited in the TUI.

### Shared local context helpers

Move reusable Git and editor-launch behavior out of `friction.cli` into adapter
helpers under `friction.interfaces`. The CLI must continue to use the same
helpers after the refactor.

The Git context helper accepts a working directory and returns best-effort
`git_root`, `git_repo`, `git_branch`, and `git_commit` values. Git absence,
non-repository directories, detached HEAD, and individual Git command failures
must produce `None` for unavailable values rather than failing capture.

For v1 JSON capture, if `cwd` is provided and one or more Git fields are absent,
the CLI adapter fills only the absent fields from this helper. Explicit JSON
values always win. This lets thin editor clients send buffer context without
duplicating Git discovery. Document this additive behavior in
`docs/json-contract.md` when it is implemented.

The editor helper preserves the existing resolution order:

1. `FRICTION_EDITOR`;
2. `VISUAL`;
3. `EDITOR`.

It parses the command without a shell and passes `+LINE[:COLUMN]`. TUI source
opening must use this helper and the same path-or-working-directory fallback as
the CLI.

### Errors and concurrency

Every mutating interface operation uses the revision displayed or read before
the operation. No adapter may silently fetch a new revision and retry after a
`revision_conflict`.

Expected domain errors retain the codes defined in `friction.domain.errors`.
Interface-specific validation errors use `validation_error`. Unexpected
database and operating-system errors use `storage_error`; tracebacks may be
logged to stderr in development but must not be placed in user-facing results.

## Terminal User Interface

### Entry point and module layout

Add the Typer subcommand:

```shell
friction tui
```

The command accepts no interface-specific options in this milestone. The root
`--db` option remains available. The command lazily imports the Textual adapter
so ordinary CLI startup does not import Textual.

Use this module layout:

```text
src/friction/interfaces/
├── context.py          # shared Git context
├── editor.py           # shared editor resolution and launch
└── tui/
    ├── __init__.py     # run_tui public entry point
    ├── app.py          # FrictionTui application and state
    ├── screens.py      # forms, filters, confirmation, help
    └── widgets.py      # item table and detail/history widgets
```

Keep Textual CSS in Python `CSS` strings for this milestone. This avoids wheel
package-data ambiguity. `run_tui(database_path)` constructs the concrete
service once and runs `FrictionTui`. `FrictionTui` must also accept an injected
service or service factory for tests.

### Main screen

At terminal widths of at least 100 columns, render:

```text
┌ Friction ─ filters/search summary ─ database basename ───────────┐
│ Item table (approximately 58%) │ Detail and history (42%)        │
│                                │                                  │
│                                │                                  │
├────────────────────────────────┴──────────────────────────────────┤
│ key hints / result count / last refresh / transient status       │
└───────────────────────────────────────────────────────────────────┘
```

Below 100 columns, stack the item table above the detail pane. Below 24 rows,
hide event payloads before hiding core item fields. The app must remain usable
at Textual's default test size of 80 by 24.

The item table contains these columns in this order:

1. status as `OPEN`, `DONE`, or `DISM`;
2. the first logical line of the note, clipped visually but not in state;
3. source;
4. repository, using `git_repo` and falling back to `-`;
5. comma-separated tags;
6. local-time `created_at` formatted `YYYY-MM-DD HH:MM`;
7. the first eight UUID characters.

Archived rows include an `ARCH` marker next to the status. The selected row is
tracked by full UUID, never by row number or UUID prefix.

The detail pane shows the complete note followed by status, revision, source,
created/updated/archive timestamps, tags, path with line and column, cwd,
filetype, Git fields, pretty-printed metadata, and chronological event history.
Event rows show timestamp, event type, revision change, and pretty-printed
payload. Missing values render as `-`.

Empty results render `No matching friction items`. Initial or refreshed load
errors render an error banner while preserving the last successfully loaded
rows. A failure before the first successful load renders a fatal screen with
retry and quit actions.

### Query state and pagination

The initial query is identical to plain `friction list`: all statuses, all
sources, active items only, no repo/tag filter, no search text, newest creation
first.

The filter screen contains:

- search text;
- zero or more statuses;
- zero or more sources;
- optional exact repository filter;
- zero or more tags, all of which must match;
- archive visibility: active, archived, or all.

Submitting filters resets offset and selection, closes the screen, and loads
the first page. Clearing filters restores the initial query. Search text is
debounced for 300 milliseconds; blank search uses `service.list`, and nonblank
search uses `service.search`.

Use a page size of 100. Loading the final visible row fetches the next page if
the previous page contained 100 items. Append pages without duplicating UUIDs.
A refresh discards accumulated pages and reloads the same number of 100-item
pages that were loaded before the refresh, with a minimum of one page. Preserve
the selected UUID if it remains in those results; otherwise select the first
row.

Make pagination deterministic by adding an ID tie-breaker to storage ordering:

- list: `created_at DESC, id DESC`;
- search: FTS relevance followed by `item_id ASC` for equal rank.

This ordering change is part of the milestone and requires repository tests,
but no database migration.

### Refresh behavior

Refresh after every successful mutation and whenever the application resumes
after source opening. Also poll every five seconds so writes made by MCP, Emacs,
or another CLI process appear without a restart.

Do not run a periodic refresh while a form, confirmation screen, or filter
screen is open. Only one list/search refresh worker may run at a time; a newer
request increments a generation counter, cancels the older worker, and ignores
any result whose generation is no longer current. Preserve selection by UUID.
If the selected item no longer matches the active filter, select the first
remaining row and show a short status message.

All synchronous service and storage calls run in Textual workers rather than on
the UI message loop. Disable the relevant action while its worker is running so
double key presses cannot submit the same mutation twice.

### Forms

Use Textual modal screens for add and edit. Both forms support keyboard and
mouse operation and contain the following fields:

| Field | Add default | Edit behavior |
| --- | --- | --- |
| note | empty, required, multiline | current note, required, multiline |
| tags | empty comma-separated input | current tags |
| path | empty | current value |
| line | empty positive integer | current value |
| column | empty positive integer | current value |
| cwd | launch working directory | current value |
| filetype | empty | current value |
| git root | discovered from cwd | current value |
| git repository | discovered from cwd | current value |
| git branch | discovered from cwd | current value |
| git commit | discovered from cwd | current value |
| metadata | `{}` as a JSON object | pretty-printed current object |

Context and metadata fields are in an initially collapsed `Advanced` section.
Tags are split on commas, whitespace-trimmed, and passed to the domain for its
normal case-insensitive de-duplication and sorting.

Validation occurs before starting a worker. A note containing only whitespace
is invalid. Line and column must be empty or positive integers. Metadata must
parse as one JSON object, not a list or primitive. Validation errors are shown
next to the relevant field and do not close the form.

On add, recompute Git defaults when the user changes cwd and explicitly invokes
the `Refresh Git context` button. Do not overwrite manually edited Git fields.
Submit a `CreateItem` with `source=ItemSource.CLI` and
`metadata.interface="tui"`.

On edit, capture the item's revision when opening the form and pass it as
`expected_revision`. Only changed fields are included in `ItemPatch`. Allow
nullable context fields to be cleared. Source, ID, status, archive state, and
timestamps are read-only and never included in a generic update.

If an edit conflicts, keep the form and its draft open, show the expected and
actual revisions, and offer `Reload latest` or `Cancel`. Reloading replaces the
form with current persisted values; it never reapplies the draft automatically.
Closing a dirty form requires confirmation.

### Actions and keys

Implement these bindings:

| Key | Action |
| --- | --- |
| `up` / `k` | select previous item |
| `down` / `j` | select next item |
| `enter` | focus or expand item details |
| `/` | focus search input |
| `f` | open complete filter screen |
| `ctrl+r` | refresh now |
| `a` | add an item |
| `e` | edit selected item |
| `d` | mark selected open item done |
| `x` | dismiss selected open item |
| `r` | reopen selected done or dismissed item |
| `A` | archive selected active item |
| `U` | unarchive selected archived item |
| `o` | open selected source in configured editor |
| `?` | show key and lifecycle help |
| `escape` | close the top modal or leave the focused search field |
| `q` | quit when no modal or dirty form is open |

Lifecycle actions that are invalid for the selected state are disabled and
their key press shows a transient explanation. Done, dismiss, and reopen do not
ask for confirmation. Archive asks for confirmation. Unarchive does not.

Every lifecycle and archive action uses the selected item's displayed revision.
On conflict, reload the item and show the expected and actual revisions without
retrying the action.

The `o` action is disabled when neither `path` nor `cwd` is present. Suspend
Textual rendering while a terminal editor is active, call the shared editor
launcher, then resume and refresh. Editor lookup or launch failure is a
recoverable banner error, not an app crash.

### TUI non-goals

Do not add dashboards, charts, drag-and-drop, saved views, custom themes,
multi-select, bulk archive, import/export screens, backup screens, database
configuration screens, or mouse-only interactions in this milestone. Existing
CLI commands remain the interface for maintenance and bulk operations.

## Emacs Capture Minor Mode

### Package placement and compatibility

Add:

```text
integrations/emacs/friction.el
tests/emacs/friction-test.el
```

`friction.el` is a single self-contained file using lexical binding and only
built-in Emacs libraries (`json`, `subr-x`, and process APIs). Its package
header requires Emacs 29.1. It is intended for local installation from this
repository; publishing to MELPA is out of scope.

Define these public symbols:

- customization group `friction`;
- `friction-executable`, default `"friction"`;
- `friction-database-file`, default `nil`, meaning normal database resolution;
- command `friction-capture`;
- buffer-local minor mode `friction-mode`;
- globalized minor mode `global-friction-mode`.

The minor-mode keymap binds only `C-c f c` to `friction-capture`. Do not claim
`SPC ?` or any Doom/General leader key in the package. The mode has no lighter
and performs no background work when enabled.

### Capture interaction

`friction-capture` performs this sequence:

1. Snapshot the originating buffer and point before opening the minibuffer.
2. Verify that `friction-executable` resolves with `executable-find`; otherwise
   raise `user-error` without starting a process.
3. Prompt with `Friction note: ` using `read-string`.
4. Reject a note that is empty after trimming.
5. Build a JSON v1 add request from the snapshot.
6. Start the CLI asynchronously, write the JSON request to stdin, and close
   stdin.
7. Return control to Emacs immediately.
8. Report success or failure when the process exits.

The command also accepts an optional NOTE argument when called from Lisp. This
path skips the minibuffer and supports multiline strings. Notes, paths, and all
other data are sent only through stdin; the note must never appear in process
arguments or a temporary file.

The payload is:

```json
{
  "schema_version": 1,
  "data": {
    "note": "...",
    "source": "emacs",
    "path": "/absolute/file/or/null",
    "line": 1,
    "column": 1,
    "cwd": "/absolute/default-directory",
    "filetype": "python-mode",
    "metadata": {
      "emacs.buffer_name": "example.py"
    }
  }
}
```

Omit unavailable optional fields instead of sending empty strings. `line` and
`column` are one-based. `path` is the expanded `buffer-file-name` when present.
`cwd` is expanded `default-directory` with its directory-file-name form.
`filetype` is the current `major-mode` symbol name. Buffer name is metadata,
not a substitute for a file path. The JSON CLI performs best-effort Git context
enrichment from cwd as specified above.

The process command is exactly:

```text
friction [--db DATABASE] add --input-json - --output json
```

Place the root `--db` option before `add`. Include it only when
`friction-database-file` is non-nil. Use `make-process` with a pipe connection,
separate stdout and stderr buffers, UTF-8 coding, and a unique process name so
multiple captures may be in flight simultaneously.

On a successful exit, parse the JSON v1 envelope, verify `schema_version == 1`,
verify `error` is null, and show `Friction captured: ID-PREFIX` using the first
eight UUID characters. On nonzero exit, malformed JSON, schema mismatch, or a
non-null error, show one `display-warning` containing the stable error code and
message when available. Include at most the first 2,000 stderr characters when
no envelope can be parsed. Kill private process buffers after handling the
result.

Do not retry automatically. A failed capture remains only in minibuffer history;
it must not fall back to the old JSONL implementation because that could create
duplicates after a partial success.

### Emacs installation and cutover example

Document a generic local installation:

```elisp
(add-to-list 'load-path "/path/to/friction/integrations/emacs")
(require 'friction)
(global-friction-mode 1)
```

Document, but do not apply, this Doom-style cutover:

```elisp
(map! :leader
      :desc "Capture friction"
      "?" #'friction-capture)
```

The cutover instructions must explicitly say to remove or disable the previous
direct JSONL writer before enabling the new binding. Keeping both writers bound
is not a supported fallback strategy.

### Emacs non-goals

Do not implement an item list, search, status transitions, editing, source
opening, history, tabulated-list mode, Transient UI, completion integration, or
automatic package installation. These are separate future decisions.

## MCP Stdio Server

### Transport and startup

Add the Typer subcommand:

```shell
friction mcp
```

It accepts no transport, host, port, authentication, or daemon flags. It creates
the service, applies migrations, creates one FastMCP server named `friction`,
and runs it with stdio transport. Do not expose SSE or Streamable HTTP code paths
even behind an undocumented flag.

Use the stable MCP SDK 1.x `FastMCP` API from `mcp.server.fastmcp`. Isolate SDK
wiring so migration to MCP SDK 2.x can be done later without changing the
application service or tool implementations.

Use this module layout:

```text
src/friction/interfaces/mcp/
├── __init__.py       # run_mcp public entry point
├── models.py         # MCP-specific structured input/output models
├── operations.py     # service-backed operations without decorators
└── server.py         # FastMCP creation and registrations
```

`create_mcp_server(service)` returns the configured server for tests.
`run_mcp(database_path)` creates the concrete service and starts stdio. Do not
create a service or touch the user's database at module import time.

Stdout belongs exclusively to MCP protocol frames. Configure all logging and
diagnostics to stderr. Never print notes, resource contents, tracebacks, startup
banners, or migration messages to stdout.

### Structured output

Reuse `ItemData` and `EventData` as the canonical item and event shapes. MCP
success values are direct structured output and are not wrapped in the CLI
`ApiEnvelope`.

Add interface-specific Pydantic response models:

```text
McpItemPage
  items: list[ItemData]
  count: int              # items in this response
  limit: int
  offset: int
  has_more: bool

McpItemDetail
  item: ItemData
  events: list[EventData]

McpEventHistory
  item_id: UUID
  events: list[EventData]
```

All models forbid unknown fields. Datetimes remain RFC 3339 UTC values and IDs
remain full UUIDs in output. Input identifiers may be full UUIDs or unambiguous
prefixes, exactly like the application service.

For expected failures, return an MCP tool error with `isError=true`, a concise
text message, and structured content matching the existing `ApiError` fields:

```json
{
  "code": "revision_conflict",
  "message": "...",
  "details": {
    "item_id": "...",
    "expected_revision": 2,
    "actual_revision": 3
  }
}
```

Implement this with a shared result/error conversion helper rather than
duplicating `try/except` blocks in every tool. Validation errors use
`validation_error`. Domain errors preserve their stable code. Unexpected errors
are logged to stderr and returned as `storage_error` without a traceback.

### Pagination and filters

List and search use these common inputs:

- `statuses`: zero or more of `open`, `done`, `dismissed`;
- `sources`: zero or more known `ItemSource` values;
- `repo`: optional exact repository filter;
- `tags`: zero or more tags, all required to match;
- `archive`: `active`, `archived`, or `all`, default `active`;
- `limit`: 1 through 200, default 50;
- `offset`: nonnegative, default 0.

Determine `has_more` by asking the service for `limit + 1` items and omitting
the extra item from output. List ordering and search ranking follow the stable
repository rules defined in the TUI section.

### Tools

Register exactly these tool names. Tool descriptions must include lifecycle and
revision requirements so an MCP client can use them without external prose.

#### `friction_add`

Inputs:

- required `note`;
- optional `path`, `line`, `column`, `cwd`, `filetype`;
- optional `git_root`, `git_repo`, `git_branch`, `git_commit`;
- `tags`, default empty;
- `metadata`, default empty object.

Force `source=mcp`; do not accept source or timestamps from the caller. Return
`ItemData`. The note must be nonblank, line and column must be positive, and Git
context may be enriched from cwd when fields are absent.

#### `friction_list`

Accept the common filter and pagination inputs and return `McpItemPage`.

#### `friction_search`

Accept required nonblank `query` plus the common filter and pagination inputs.
Return `McpItemPage` in FTS relevance order.

#### `friction_get`

Accept `identifier` and optional `include_history`, default false. Return
`McpItemDetail`; `events` is empty unless history was requested.

#### `friction_update`

Accept required `identifier` and positive `revision`, plus optional patchable
fields from `UpdateData`. Require at least one actual field operation.

Because ordinary optional MCP arguments cannot distinguish omission from an
explicit JSON null reliably across hosts, add `clear_fields`, default empty.
It may contain only `path`, `line`, `column`, `cwd`, `filetype`, `git_root`,
`git_repo`, `git_branch`, or `git_commit`. A field may not be both supplied and
listed for clearing. Clear tags with `tags=[]` and metadata with `metadata={}`;
note cannot be cleared. Return updated `ItemData`.

#### `friction_mark_done`

Accept `identifier` and positive `revision`. Move an open item to done and
return `ItemData`.

#### `friction_dismiss`

Accept `identifier` and positive `revision`. Move an open item to dismissed and
return `ItemData`.

#### `friction_reopen`

Accept `identifier` and positive `revision`. Move a done or dismissed item to
open and return `ItemData`.

#### `friction_archive`

Accept `identifier` and positive `revision`. Archive one item without changing
its status and return `ItemData`. MCP does not expose bulk archive.

#### `friction_unarchive`

Accept `identifier` and positive `revision`. Restore one archived item without
changing its status and return `ItemData`.

#### `friction_history`

Accept `identifier` and return `McpEventHistory` in chronological event order.

Do not register an editor-opening tool, import/export tools, backup, doctor,
bulk mutation, arbitrary SQL, database-path mutation, file reads, or shell
execution.

### Resources

Register these resource URIs with MIME type `application/json`:

#### `friction://items/{identifier}`

Return the canonical item and complete event history as `McpItemDetail`.
Identifier resolution follows service rules. This is a resource template, not
one registered resource per database row.

#### `friction://views/open`

Return the first 100 active open items as `McpItemPage`, offset 0, using list
ordering. It is a snapshot each time the resource is read.

#### `friction://views/recent`

Return the first 50 active items across all statuses as `McpItemPage`, offset 0,
using list ordering. It is a snapshot each time the resource is read.

#### `friction://schema`

Return a JSON object containing:

- `schema_version: 1`;
- JSON Schema generated from `ItemData`, `EventData`, and `ApiError`;
- the exact tool names;
- the lifecycle transition map;
- the archive visibility values;
- the statement that mutation revisions are mandatory.

Resource reads never mutate data. Expected lookup errors use MCP resource error
handling and retain the stable code in the error message.

### Prompt

Register one prompt named `triage_friction` with optional `repo`, optional
`tag`, and `limit` from 1 through 100, default 50.

At invocation time, fetch active open items matching the filters and return a
user message containing their canonical JSON plus these instructions:

```text
Review these open friction items. Group related symptoms, identify likely
root causes, call out repeated repositories or tags, and propose a prioritized
action list. Do not change item status unless the user explicitly asks you to
use a mutation tool.
```

When there are no matches, the prompt says so and still includes an empty JSON
array. The prompt itself is read-only and must never call mutation methods.

### MCP trust boundary

The server is intended for an MCP host running as the same local user. It has
the same database access as that user. There is no additional confirmation
inside mutation tools; approval and tool policy belong to the MCP host.

The server must not bind a socket. It must not advertise HTTP or remote setup.
Documentation must warn that configuring a host grants it access to private
notes and the explicitly exposed mutations.

Provide a generic host configuration example using the installed long command:

```json
{
  "mcpServers": {
    "friction": {
      "command": "friction",
      "args": ["mcp"]
    }
  }
}
```

For a nondefault database, the argument order is
`["--db", "/absolute/path/friction.db", "mcp"]`.

## Repository Changes

The completed milestone should have this relevant shape:

```text
friction/
├── integrations/
│   └── emacs/
│       └── friction.el
├── src/friction/interfaces/
│   ├── context.py
│   ├── editor.py
│   ├── tui/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── screens.py
│   │   └── widgets.py
│   └── mcp/
│       ├── __init__.py
│       ├── models.py
│       ├── operations.py
│       └── server.py
├── tests/
│   ├── emacs/friction-test.el
│   ├── integration/test_interface_commands.py
│   ├── integration/test_mcp.py
│   ├── integration/test_tui.py
│   └── unit/
│       ├── test_context.py
│       ├── test_mcp_operations.py
│       └── test_tui_state.py
└── docs/
    └── interfaces.md
```

Use the listed production and primary test files. Additional test files are
allowed only for existing repository categories such as contract, package, or
migration tests; do not merge the three interface test suites together.

Update these durable documents in the same implementation commits:

- `README.md`: installation and launch examples;
- `docs/architecture.md`: implemented adapter graph and remaining non-goals;
- `docs/cli.md`: `tui` and `mcp` commands plus database option placement;
- `docs/json-contract.md`: best-effort Git enrichment for machine capture;
- `docs/validation.md`: TUI, MCP, and Emacs checks;
- this document: change planned language to implemented status only after all
  acceptance criteria pass.

## Implementation Sequence

The implementation agent must use this sequence and leave each step in a
reviewable commit:

1. **Shared adapter helpers**
   - move Git and editor helpers out of `cli.py`;
   - preserve existing CLI behavior and tests;
   - add JSON capture Git enrichment and contract tests;
   - add deterministic repository tie-breakers.
2. **TUI**
   - add Textual dependency and lockfile update;
   - implement state, screens, workers, refresh, forms, and actions;
   - add unit and Textual Pilot integration tests;
   - document launch and keys.
3. **Emacs capture**
   - add the self-contained Elisp package and ERT tests;
   - add installation and cutover documentation;
   - add Emacs 29 to CI without changing the external configs repository.
4. **MCP stdio**
   - add the stable MCP SDK dependency and lockfile update;
   - implement operation functions, models, server wiring, tools, resources,
     prompt, and error mapping;
   - add in-process tests and a real stdio subprocess smoke test;
   - document host configuration and trust boundary.
5. **Release validation**
   - run the complete validation matrix;
   - build and install the wheel in an isolated environment;
   - smoke-test packaged `tui` and `mcp` entry paths with a temporary database;
   - inspect the final diff and repository status.

Do not combine all work into one commit. Commit messages remain concise English
imperatives or conventional-style titles matching the existing history.

## Test Matrix

### Shared Python behavior

Add tests for:

- database option and environment precedence for both commands;
- migration on fresh and already-current temporary databases;
- missing Git, non-Git cwd, branch, detached HEAD, and explicit-field override;
- CLI behavior remaining unchanged after helper extraction;
- deterministic list and search ordering when primary sort values tie;
- JSON v1 remaining backward compatible.

### TUI tests

Use Textual's `App.run_test()` and Pilot. Tests use injected services or
temporary databases and must cover:

- empty, populated, narrow, and short main-screen rendering;
- default active/all-status query;
- search debounce and every filter;
- pagination without duplicate IDs;
- selection preservation across refresh;
- external database write appearing after refresh;
- add and edit validation, success, cancellation, and dirty-close confirmation;
- every valid and invalid lifecycle action;
- archive confirmation and unarchive;
- revision conflict without automatic retry;
- periodic worker exclusivity and stale-result suppression;
- editor open success, missing editor, and item without source context;
- fatal initial load and recoverable later load errors;
- all documented keyboard bindings.

Do not add snapshot tests in this milestone. Assert widget state and behavior
with synthetic fixtures so tests never encode machine-specific paths or
timestamps.

### Emacs ERT tests

Run Emacs with `--batch -Q`. ERT tests must cover:

- command construction with and without a database override;
- JSON payload for file and non-file buffers;
- one-based line and column;
- Unicode, quotes, backslashes, and programmatic multiline notes;
- whitespace-only rejection;
- missing executable;
- asynchronous stdin delivery with no note in argv;
- success envelope, domain error envelope, malformed output, and nonzero exit;
- cleanup of private stdout/stderr buffers;
- simultaneous captures using unique process names;
- local and global minor-mode bindings.

The CI command is:

```shell
emacs --batch -Q \
  -L integrations/emacs \
  -l tests/emacs/friction-test.el \
  -f ert-run-tests-batch-and-exit
```

Install Emacs in the macOS CI job with `brew install emacs`, verify that
`emacs --version` reports 29.1 or newer, and then run the ERT command. Do not
rely on the operating system's bundled Emacs version.

### MCP tests

Test pure operation functions separately from SDK registration. Then use the
official SDK client against `create_mcp_server(service)` and cover:

- exact tool, resource, resource-template, and prompt discovery names;
- generated input schemas and structured output;
- add source forced to MCP;
- every list/search filter and pagination boundary;
- item get with and without history;
- update, field clearing, and empty-update validation;
- every lifecycle mutation and archive operation;
- stale revision error code and details with no retry;
- not-found, ambiguous-prefix, validation, and unexpected-storage errors;
- resource JSON and MIME types;
- triage prompt filtering and read-only behavior;
- no database access at import time.

Add one subprocess smoke test that starts:

```shell
friction --db TEMP_DB mcp
```

Connect over stdio with the official client, initialize the session, list tools,
call `friction_add`, call `friction_get`, and shut down cleanly. Assert that
protocol parsing succeeds, which also proves stdout was not polluted.

### Validation commands

The final implementation must pass:

```shell
uv lock --check
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=friction --cov-report=term-missing --cov-fail-under=90
uv run pytest tests/migration
emacs --batch -Q -L integrations/emacs \
  -l tests/emacs/friction-test.el -f ert-run-tests-batch-and-exit
uv run friction --help
uv build
git diff --check
git status --short
```

Elisp files must also byte-compile without warnings under Emacs 29. Python tests
must not read or modify the user's real database or friction log.

## Definition of Done

The milestone is complete only when all of the following are true:

1. `uv tool install .` installs working `friction tui` and `friction mcp`
   commands without extras.
2. TUI performs every specified single-item operation and displays history.
3. TUI observes an external write without restart and never blocks its event
   loop on database work.
4. TUI and MCP reject stale revisions without automatic retry.
5. `friction-capture` returns control immediately, sends JSON through stdin,
   records Emacs buffer context, and reports the persisted item ID.
6. Enabling the Emacs package cannot write legacy JSONL.
7. MCP exposes exactly the specified stdio tools, resources, and prompt, with no
   network listener.
8. MCP stdout contains only protocol traffic.
9. Items created through TUI, Emacs, and MCP are immediately queryable through
   the existing CLI and have the specified source attribution.
10. Every mutation creates the existing correct event and revision increment.
11. The wheel contains all Python adapter modules and the repository contains
    the standalone Emacs file.
12. Documentation, dependency lock, CI, tests, and commits are complete, all
    validation passes, and the worktree contains no private data or caches.

There are no intentionally unresolved product decisions inside this milestone.
If implementation reveals a conflict with an existing documented contract, the
agent must preserve the existing contract, document the conflict, and stop that
specific portion for review rather than silently choosing new behavior.

## Framework References

- [Textual testing guide](https://textual.textualize.io/guide/testing/)
- [MCP Python SDK stable v1 branch](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
- [GNU Emacs minor-mode definition](https://www.gnu.org/software/emacs/manual/html_node/elisp/Defining-Minor-Modes.html)
