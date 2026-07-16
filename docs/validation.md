# Validation

Run checks from the repository root:

```shell
uv lock --check
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=friction --cov-report=term-missing --cov-fail-under=90
uv run alembic upgrade head
uv run friction --help
git diff --check
git status --short
```

Tests use temporary databases and synthetic JSONL fixtures. Validation against
the user's real `~/friction-log` must use dry-run or a temporary database and
must not print note contents.

