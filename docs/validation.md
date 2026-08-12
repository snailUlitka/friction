# Validation

Run checks from the repository root:

```shell
uv lock --check
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=friction --cov-report=term-missing --cov-fail-under=90
uv run pytest tests/migration
emacs --batch -Q -L integrations/emacs \
  -l tests/emacs/friction-test.el -f ert-run-tests-batch-and-exit
uv run friction --help
uv run friction tui --help
uv run friction mcp --help
uv build
git diff --check
git status --short
```

GitHub Actions runs the same sequence on `macos-latest` with Python 3.12, then
builds the wheel and smoke-tests packaged migrations through `doctor`. Emacs
validation requires GNU Emacs 30.2 or newer and byte-compiles `friction.el`
with warnings treated as errors.

A release acceptance run also installs the project with `uv tool install .`,
installs the built wheel into a fresh environment, starts packaged `tui` in a
PTY, and performs an MCP stdio handshake plus capture against temporary
databases. Keep the tool directory, environments, caches, and databases under a
repository-local ignored temporary directory during this check.

Tests use temporary databases and synthetic JSONL fixtures. Validation against
the user's real `~/friction-log` must use dry-run or a temporary database and
must not print note contents.

For a local migration acceptance check:

```shell
uv run friction --db /tmp/friction-acceptance.db import-jsonl ~/friction-log --dry-run --output json
```
