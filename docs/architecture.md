# Architecture

Friction is a layered Python package with a single domain and application core.

```text
CLI / JSON / Textual adapters
             |
Application service and repository protocol
        |
Domain models and lifecycle rules
        |
SQLAlchemy repository / SQLite / Alembic

Emacs capture mode -> CLI JSON v1 -> application service
```

Dependencies point inward. Domain and application code do not import Typer,
SQLAlchemy, Alembic, or future interface frameworks. Adapters call the public
application service; they never issue SQL or reimplement status transitions.

The default database is
`~/Library/Application Support/friction/friction.db`. A command-level `--db`
option has highest precedence, followed by `FRICTION_DB_PATH`, then the default.
SQLite runs with foreign keys, WAL, and a five-second busy timeout. Packaged
Alembic migrations are applied before normal database-backed commands; tests
validate both fresh and repeated upgrades.

The Textual TUI is an implemented local adapter over the public application
service. The standalone Emacs mode is a thin asynchronous client of the JSON
CLI and never opens SQLite. MCP remains in progress for the interface milestone
specified in `interfaces.md`. FastAPI, web, Neovim, and network MCP remain
outside that milestone.
