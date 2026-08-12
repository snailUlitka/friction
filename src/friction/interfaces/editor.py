"""Shared editor resolution and source-opening behavior."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from friction.domain import FrictionError, FrictionItem


class EditorError(FrictionError):
    """A recoverable editor or source-location error."""

    code = "validation_error"


def editor_command(environment: Mapping[str, str] | None = None) -> list[str]:
    """Resolve the configured editor without invoking a shell."""
    environ = os.environ if environment is None else environment
    for variable in ("FRICTION_EDITOR", "VISUAL", "EDITOR"):
        value = environ.get(variable, "").strip()
        if value:
            command = shlex.split(value)
            if command and shutil.which(command[0]) is not None:
                return command
            raise EditorError(f"Editor from {variable} is not executable.")
    raise EditorError("Set FRICTION_EDITOR, VISUAL, or EDITOR first.")


def launch_editor(
    target: Path,
    *,
    line: int | None = None,
    column: int | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Open a path at an optional one-based position."""
    command = editor_command(environment)
    position: list[str] = []
    if line is not None:
        suffix = f":{column}" if column is not None else ""
        position = [f"+{line}{suffix}"]
    result = subprocess.run([*command, *position, str(target)], check=False)
    if result.returncode != 0:
        raise EditorError(f"Editor exited with status {result.returncode}.")


def resolved_source(item: FrictionItem) -> Path:
    """Resolve the path-or-working-directory fallback for one item."""
    raw_target = item.path or item.cwd
    if raw_target is None:
        raise EditorError("This item has no source path or working directory.")
    target = Path(raw_target).expanduser()
    if not target.is_absolute() and item.cwd:
        target = Path(item.cwd).expanduser() / target
    target = target.resolve()
    if not target.exists():
        raise EditorError(f"Source path does not exist: {target}")
    return target
