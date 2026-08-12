"""Best-effort local source-control context for capture adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_CONTEXT_FIELDS = (
    "git_root",
    "git_repo",
    "git_branch",
    "git_commit",
)


def _git_value(cwd: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def git_context(cwd: str | Path) -> dict[str, str | None]:
    """Return available Git context without making capture depend on Git."""
    working_directory = Path(cwd).expanduser().resolve()
    root = _git_value(working_directory, "rev-parse", "--show-toplevel")
    if root is None:
        return dict.fromkeys(GIT_CONTEXT_FIELDS)
    root_path = Path(root).resolve()
    return {
        "git_root": str(root_path),
        "git_repo": root_path.name,
        "git_branch": _git_value(root_path, "branch", "--show-current"),
        "git_commit": _git_value(root_path, "rev-parse", "HEAD"),
    }


def missing_git_context(
    cwd: str | Path | None,
    *,
    supplied_fields: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str | None]:
    """Discover only Git fields omitted by a thin capture client."""
    if cwd is None:
        return {}
    discovered = git_context(cwd)
    return {
        field: value
        for field, value in discovered.items()
        if field not in supplied_fields
    }
