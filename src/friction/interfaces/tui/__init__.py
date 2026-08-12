"""Public Textual adapter entry point."""

from pathlib import Path

from friction.interfaces.tui.app import FrictionTui
from friction.storage import create_service, resolve_database_path

__all__ = ["FrictionTui", "run_tui"]


def run_tui(database_path: str | Path | None = None) -> None:
    """Apply migrations, construct one service, and run the terminal UI."""
    resolved = resolve_database_path(database_path)
    service = create_service(resolved)
    FrictionTui(service, database_path=resolved).run()
