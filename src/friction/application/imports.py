"""Import records and the persistence port used by JSONL adapters."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from friction.domain.models import FrictionEvent, FrictionItem


@dataclass(frozen=True)
class ImportProvenance:
    """Source identity for one normalized record."""

    source_path: Path
    source_line: int
    source_format: str
    fingerprint: str
    raw_sha256: str
    imported_at: datetime


@dataclass(frozen=True)
class ImportRecord:
    """One normalized item, event, and source provenance."""

    item: FrictionItem
    event: FrictionEvent
    provenance: ImportProvenance


@dataclass(frozen=True)
class StoredImportResult:
    """Persistence counts for one source file."""

    imported: int
    skipped: int


class ImportRepository(Protocol):
    """Atomic import capability implemented by SQLite storage."""

    def import_records(self, records: tuple[ImportRecord, ...]) -> StoredImportResult:
        """Persist one validated source file atomically."""
