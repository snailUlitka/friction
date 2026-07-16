# Friction

Friction is a private, local-first tracker for small workflow annoyances. It
provides one Python application service and SQLite database behind a human CLI
and a versioned JSON interface.

The first release covers the domain core, the `fr`/`friction` CLI, migration of
the existing JSONL logs, canonical JSONL export, and SQLite backups. Editor,
MCP, and web adapters are intentionally deferred until the v1 contract settles.

## Development

```shell
uv sync --dev
uv run pytest
uv run friction --help
```

The supported runtime is Python 3.12+ on macOS. See [docs/README.md](docs/README.md)
for the architecture and validation map.

