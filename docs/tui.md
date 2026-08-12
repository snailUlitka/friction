# Terminal User Interface

Launch the full single-item interface with `friction tui`. The root `--db`
option and `FRICTION_DB_PATH` use the same precedence as every other command.
The TUI applies migrations before startup and calls `FrictionService` directly;
it does not spawn the CLI or issue SQL.

The main view shows active items newest first, complete item details, metadata,
and chronological history. Terminals narrower than 100 columns stack details
below the table. Results are loaded in deterministic pages of 100.

## Normal mode

The interface starts in Vim-style normal mode:

| Key | Action |
| --- | --- |
| `j` / `k` | next / previous item |
| `gg` / `G` | first / last loaded item |
| `ctrl+d` / `ctrl+u` | half-page down / up |
| `l` / `h` | focus details / table |
| `/` | edit search; Enter applies it |
| `a` / `i` | add / edit |
| `gf` | open source in the configured editor |
| `za` | archive or unarchive |
| `:` | open the command line |
| `?` | show help |
| `escape` | cancel a prefix or return to normal mode |

Prefixes expire after one second. The command line accepts exactly `:e`, `:q`,
`:add`, `:edit`, `:done`, `:dismiss`, `:reopen`, `:archive`, `:unarchive`,
`:open`, `:filters`, and `:help`. Its in-memory history is limited to 50
commands and is navigated with `k` and `j`.

## Forms and concurrency

Add, edit, and filter forms support the mouse plus Vim-style field navigation:
`j`/`k` select a field, `i` or Enter edits it, and Escape returns to form normal
mode. Form commands are `:w`, `:wq`, and `:q`. Advanced item fields contain
source context, Git context, and JSON metadata. Add always reserves
`metadata.interface="tui"` while retaining `source="cli"` for JSON v1
compatibility.

Every mutation uses the revision displayed when the operation began. A stale
edit keeps its draft open and offers to replace it with the latest persisted
values. Lifecycle conflicts are reported and reloaded without retrying the
mutation. External writes are intentionally visible only after explicit `:e`;
the TUI does not poll the database.
