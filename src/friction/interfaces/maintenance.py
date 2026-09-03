"""SQLite backup and installation diagnostics."""

from __future__ import annotations

import os
import shlex
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from friction.domain import StorageError
from friction.storage import create_sqlite_engine, current_revision, upgrade_database
from friction.storage.sqlite import database_sha256, resolve_database_path

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BackupResult:
    """Verified SQLite backup metadata."""

    path: Path
    size: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {"path": str(self.path), "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class DoctorCheck:
    """One diagnostic result."""

    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class DoctorReport:
    """Complete installation and database diagnosis."""

    ok: bool
    database_path: Path
    checks: tuple[DoctorCheck, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "database_path": str(self.database_path),
            "checks": [check.as_dict() for check in self.checks],
        }


def backup_database(
    database_path: str | Path | None,
    destination: str | Path,
    *,
    force: bool = False,
    clock: Clock = _utc_now,
) -> BackupResult:
    """Create and verify a transactionally consistent SQLite backup."""
    source = resolve_database_path(database_path)
    engine = create_sqlite_engine(source)
    upgrade_database(engine)
    engine.dispose()

    requested = Path(destination).expanduser()
    if (requested.exists() and requested.is_dir()) or not requested.suffix:
        requested.mkdir(parents=True, exist_ok=True)
        timestamp = clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = requested / f"friction-backup-{timestamp}.db"
    else:
        target = requested
        target.parent.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    if target == source:
        raise StorageError("Backup destination must differ from the live database.")
    if target.exists() and not force:
        raise StorageError(f"Backup already exists: {target}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(temporary_path) as backup_connection,
        ):
            source_connection.backup(backup_connection)
            integrity = backup_connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            if integrity is None or integrity[0] != "ok":
                raise StorageError("SQLite backup failed its integrity check.")
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return BackupResult(
        path=target,
        size=target.stat().st_size,
        sha256=database_sha256(target),
    )


def doctor_database(database_path: str | Path | None) -> DoctorReport:
    """Check schema, pragmas, integrity, FTS, Git, and editor configuration."""
    path = resolve_database_path(database_path)
    engine = create_sqlite_engine(path)
    upgrade_database(engine)
    checks: list[DoctorCheck] = []
    directory_writable = os.access(path.parent, os.W_OK)
    checks.append(
        DoctorCheck(
            "database_directory",
            "ok" if directory_writable else "warning",
            (
                str(path.parent)
                if directory_writable
                else (
                    f"{path.parent}: directory is not writable by the current "
                    "process; filesystem permissions or sandbox policy may "
                    "restrict mutations"
                )
            ),
        )
    )
    revision = current_revision(engine)
    checks.append(
        DoctorCheck(
            "schema_revision",
            "ok" if revision == "0001_initial" else "error",
            revision or "uninitialized",
        )
    )
    with engine.connect() as connection:
        pragma_values = {
            "foreign_keys": connection.execute(
                text("PRAGMA foreign_keys")
            ).scalar_one(),
            "journal_mode": connection.execute(
                text("PRAGMA journal_mode")
            ).scalar_one(),
            "busy_timeout": connection.execute(
                text("PRAGMA busy_timeout")
            ).scalar_one(),
            "integrity": connection.execute(
                text("PRAGMA integrity_check")
            ).scalar_one(),
        }
        fts_exists = connection.execute(
            text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'friction_items_fts'"
            )
        ).scalar_one()
    expected_pragmas = {
        "foreign_keys": 1,
        "journal_mode": "wal",
        "busy_timeout": 5_000,
        "integrity": "ok",
    }
    for name, expected in expected_pragmas.items():
        actual = pragma_values[name]
        checks.append(
            DoctorCheck(
                name,
                "ok" if actual == expected else "error",
                str(actual),
            )
        )
    checks.append(
        DoctorCheck("fts5", "ok" if fts_exists == 1 else "error", "available")
    )

    editor = _configured_editor()
    checks.append(
        DoctorCheck(
            "editor",
            "ok" if editor else "warning",
            editor or "FRICTION_EDITOR, VISUAL, and EDITOR are unset",
        )
    )
    git = shutil.which("git")
    checks.append(
        DoctorCheck("git", "ok" if git else "warning", git or "not installed")
    )
    engine.dispose()
    return DoctorReport(
        ok=all(check.status != "error" for check in checks),
        database_path=path,
        checks=tuple(checks),
    )


def _configured_editor() -> str | None:
    for variable in ("FRICTION_EDITOR", "VISUAL", "EDITOR"):
        value = os.environ.get(variable, "").strip()
        if not value:
            continue
        command = shlex.split(value)
        if command and shutil.which(command[0]) is not None:
            return value
    return None
