"""SQLite persistence adapter and service factory."""

from pathlib import Path

from friction.application.service import FrictionService
from friction.storage.migration_runner import current_revision, upgrade_database
from friction.storage.sqlite import (
    SQLiteItemRepository,
    create_sqlite_engine,
    default_database_path,
    resolve_database_path,
)

__all__ = [
    "SQLiteItemRepository",
    "create_repository",
    "create_service",
    "create_sqlite_engine",
    "current_revision",
    "default_database_path",
    "resolve_database_path",
    "upgrade_database",
]


def create_service(
    database_path: str | Path | None = None, *, migrate: bool = True
) -> FrictionService:
    """Build the public service backed by a SQLite database."""
    return FrictionService(create_repository(database_path, migrate=migrate))


def create_repository(
    database_path: str | Path | None = None, *, migrate: bool = True
) -> SQLiteItemRepository:
    """Build the concrete repository used by storage-aware adapters."""
    resolved = resolve_database_path(database_path)
    engine = create_sqlite_engine(resolved)
    if migrate:
        upgrade_database(engine)
    return SQLiteItemRepository(engine)
