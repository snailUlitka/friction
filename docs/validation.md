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
emacs --batch -Q --eval \
  '(progn (require (quote bytecomp)) (let ((byte-compile-error-on-warn t) (byte-compile-dest-file-function (lambda (_) (expand-file-name "friction.elc" temporary-file-directory)))) (byte-compile-file "integrations/emacs/friction.el")))'
uv run friction --version
uv run friction --help
uv run friction tui --help
uv run friction mcp --help
uv build --clear
uv run python scripts/verify_release.py
git diff --check
git status --short
```

GitHub Actions runs the Python sequence on `macos-latest` with the minimum
Python 3.12 and the current Homebrew-target Python, then builds the wheel and
smoke-tests packaged migrations through `doctor`. Emacs validation requires GNU
Emacs 30.2 or newer and byte-compiles `friction.el` with warnings treated as
errors.

A release acceptance run also installs the project with `uv tool install .`,
installs the built wheel into a fresh environment, starts packaged `tui` in a
PTY, and performs an MCP stdio handshake plus capture against temporary
databases. Keep the tool directory, environments, caches, and databases under a
repository-local ignored temporary directory during this check.

After installing the wheel into an isolated tool directory, run the packaged
interface check with its executable path:

```shell
uv run python scripts/release_acceptance.py /absolute/path/to/friction
```

For a tag, also pass it to the artifact verifier. It must match both the Python
project version and the Emacs package header:

```shell
uv run python scripts/verify_release.py --tag v0.1.0
```

Tests use temporary databases and synthetic JSONL fixtures. Validation against
the user's real `~/friction-log` must use dry-run or a temporary database and
must not print note contents.

For a local migration acceptance check:

```shell
uv run friction --db /tmp/friction-acceptance.db import-jsonl ~/friction-log --dry-run --output json
```
