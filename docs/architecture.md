# Architecture

Friction is a layered Python package with a single domain and application core.

```text
CLI / JSON adapters
        |
Application service and repository protocol
        |
Domain models and lifecycle rules
        |
SQLAlchemy repository / SQLite / Alembic
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

FastAPI, MCP, Emacs, and Neovim adapters are out of scope for v1. The public
application service and JSON contract are the extension points for those
adapters.
