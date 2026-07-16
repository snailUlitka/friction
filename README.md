# Friction

Friction is a private, local-first tracker for small workflow annoyances. It
provides one Python application service and SQLite database behind a human CLI
and a versioned JSON interface.

The first release covers the domain core, the `fr`/`friction` CLI, migration of
the existing JSONL logs, canonical JSONL export, and SQLite backups. The next
interface milestone is fully specified in
[docs/interfaces.md](docs/interfaces.md): a Textual TUI, capture-only Emacs
minor mode, and local stdio MCP server. Web, Neovim, and network adapters remain
deferred.

## Development

```shell
uv sync --dev
uv run pytest
uv run friction --help
```

Install both console scripts into an isolated user tool environment:

```shell
uv tool install .
friction --help
```

The existing Fish function named `fr` shadows the short executable until the
separate `configs` migration is performed. Use `friction` in the meantime; both
entry points run the same application.

Typical local usage:

```shell
uv run friction add "what felt slow or annoying"
uv run friction list
uv run friction search "clipboard"
uv run friction import-jsonl ~/friction-log --dry-run
```

The supported runtime is Python 3.12+ on macOS. See [docs/README.md](docs/README.md)
for the architecture and validation map.
