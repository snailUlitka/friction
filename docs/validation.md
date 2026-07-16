# Validation

Run checks from the repository root:

```shell
uv lock --check
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=friction --cov-report=term-missing --cov-fail-under=90
uv run pytest tests/migration
uv run friction --help
git diff --check
git status --short
```

Tests use temporary databases and synthetic JSONL fixtures. Validation against
the user's real `~/friction-log` must use dry-run or a temporary database and
must not print note contents.

For a local migration acceptance check:

```shell
uv run friction --db /tmp/friction-acceptance.db import-jsonl ~/friction-log --dry-run --output json
```
