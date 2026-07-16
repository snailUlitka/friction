# AGENTS.md

This repository contains Friction, a local-first workflow-friction tracker.

## How To Use This Harness

- Treat this file as the operational map; keep durable design knowledge in
  `docs/`.
- Read `docs/README.md` before changing architecture, contracts, persistence,
  or command behavior.
- Keep the domain and application layers independent of Typer, SQLAlchemy, and
  future HTTP/MCP adapters.
- Update documentation whenever a change creates a durable rule or alters a
  public contract.
- Never commit a user's database, friction log, exported notes, editor state,
  credentials, or package caches.

## Repository Map

- `src/friction/` contains domain, application, storage, contract, and CLI code.
- `alembic/` contains forward-only database migrations.
- `tests/` mirrors behavior at unit, contract, integration, and migration levels.
- `docs/` is the system of record for architecture, contracts, and operations.

## Working Rules

- Support Python 3.12 or newer on macOS.
- Use `uv` for dependency and command execution; keep `uv.lock` committed.
- Make database changes through Alembic migrations, never ad-hoc startup DDL.
- Preserve the versioned JSON contract and optimistic-concurrency semantics.
- Write code, documentation, and commit messages in English.

## Validation

- Follow `docs/validation.md` for the complete validation sequence.
- At minimum run Ruff, mypy, pytest, `git diff --check`, and inspect git status.

