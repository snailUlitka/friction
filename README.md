# Friction

Friction is a private, local-first tracker for small workflow annoyances. It
provides one Python application service and SQLite database behind a human CLI
and a versioned JSON interface.

The first release covers the domain core, the `fr`/`friction` CLI, migration of
the existing JSONL logs, canonical JSONL export, and SQLite backups. The
Textual TUI, configurable local Emacs capture mode, and local stdio MCP server
are implemented. Their shared requirements are recorded in
[docs/interfaces.md](docs/interfaces.md). Web, Neovim, and network adapters
remain deferred.

## Installation

Install the latest release with Homebrew:

```shell
brew install snailulitka/tap/friction
friction --version
friction doctor
```

Alternatively, install the same tagged release into an isolated `uv` tool
environment:

```shell
uv tool install "git+https://github.com/snailUlitka/friction.git@v0.1.0"
friction --version
friction doctor
```

The default database is
`~/Library/Application Support/friction/friction.db`. Removing or upgrading the
application does not remove this user-owned database.

The Emacs package installs directly from the same Git repository through
Emacs 30 `package-vc`; see
[integrations/emacs/README.md](integrations/emacs/README.md). The MCP server is
included in every normal Friction installation and starts with `friction mcp`.

## Development

```shell
uv sync --dev
uv run pytest
uv run friction --help
```

Install both console scripts from a checkout for local acceptance testing:

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
uv run friction tui
uv run friction mcp
uv run friction import-jsonl ~/friction-log --dry-run
```

The standalone Emacs package and its settings are documented in
[integrations/emacs/README.md](integrations/emacs/README.md).
Local MCP host configuration and its trust boundary are documented in
[docs/mcp.md](docs/mcp.md).

The supported runtime is Python 3.12+ on macOS. Friction is licensed under the
[MIT License](LICENSE). See [docs/README.md](docs/README.md) for the architecture,
release, and validation map.
