# CLI

The package installs both `fr` and `friction`; they are identical entry points.
The long name remains usable while an existing Fish function shadows `fr`.

## Database and output

Pass `--db PATH` before a subcommand to override the database for one call, or
set `FRICTION_DB_PATH`. Commands default to human output. Commands that return
data accept `--output json` and then write exactly one v1 envelope to stdout.

```shell
friction --db /tmp/friction.db add "clipboard loses formatting"
friction list --status open --tag editor
friction search "clipboard"
friction show ITEM_ID --history --output json
```

## Capture and updates

`add` accepts a positional note, an interactive prompt, `--edit`, or a v1
request via `--input-json FILE|-`. Repeat `--tag` to attach tags. Machine input
is mutually exclusive with positional and human capture options.

`update ITEM --input-json FILE|-` applies a non-lifecycle patch and requires the
current revision in its request. `done`, `dismiss`, `reopen`, `archive`, and
`unarchive` accept `--revision`; without it the human CLI reads and uses the
current revision. `edit` captures a revision before opening the editor and
rejects a stale save.

Bulk archive uses `archive --status STATUS` and requires interactive
confirmation or `--yes`. Normal list/search excludes archived items;
`--archived` selects only archived items and `--all` includes both.

## Editors

`edit` and `open` resolve the editor in this order:

1. `FRICTION_EDITOR`
2. `VISUAL`
3. `EDITOR`

The command is parsed without a shell. Source positions are passed as
`+LINE[:COLUMN]`, which is supported by Neovim and Emacs.

## Exit codes

- `0`: success
- `2`: invalid input or lifecycle transition
- `3`: missing or ambiguous item identifier
- `4`: revision conflict
- `5`: storage or operating-system failure
- `6`: import failure

## Import, export, backup, and diagnosis

```shell
friction import-jsonl ~/friction-log --dry-run
friction import-jsonl ~/friction-log
friction export --format jsonl --output backup/
friction backup backup/
friction doctor
```

Dry-run parses every source file without creating or migrating the configured
database. A real directory import commits each valid file independently and
returns exit code 6 if any file is invalid. Canonical export includes active and
archived items by default. `backup` is the complete SQLite backup including
events and import provenance; `doctor` checks schema, pragmas, integrity, FTS5,
Git, and editor configuration. Its `database_directory` check reports a
warning, while keeping the diagnostic exit code successful, when the current
process cannot write to the database directory. The warning names filesystem
permissions and sandbox policy as possible causes; it does not imply database
corruption. Schema, pragma, integrity, and FTS5 failures remain fatal. The
existing check name is retained for compatibility with the v1 JSON contract.

## Terminal interface

`friction tui` opens the Textual interface over the same database and applies
packaged migrations before the event loop starts. Put the root database option
before the subcommand:

```shell
friction tui
friction --db /tmp/friction.db tui
```

The command has no interface-specific options. See `tui.md` for its Vim-style
keys, colon commands, forms, filters, and concurrency behavior.

## MCP stdio server

`friction mcp` starts the local MCP server and owns stdout exclusively for MCP
protocol traffic. It applies migrations first and accepts no host, port,
transport, authentication, or daemon options. Put the root database option
before the subcommand:

```shell
friction mcp
friction --db /tmp/friction.db mcp
```

The command is normally launched by an MCP host rather than typed into an
interactive terminal. See `mcp.md` for host configuration, exposed operations,
and the private-data trust boundary.
