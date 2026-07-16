"""Legacy import and canonical JSONL export adapter."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from friction.application import ArchiveFilter, FrictionService, ItemQuery
from friction.application.imports import (
    ImportProvenance,
    ImportRecord,
    ImportRepository,
)
from friction.contracts import ItemData
from friction.domain import (
    EventType,
    FrictionEvent,
    FrictionItem,
    ImportFailureError,
    ItemSource,
    ItemStatus,
    StorageError,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ImportIssue:
    """Validation error tied to a source line."""

    path: Path
    line: int | None
    message: str

    def as_dict(self) -> dict[str, str | int | None]:
        return {"path": str(self.path), "line": self.line, "message": self.message}


@dataclass(frozen=True)
class ImportFilePlan:
    """Validated records or issues for one JSONL file."""

    path: Path
    records: tuple[ImportRecord, ...]
    issues: tuple[ImportIssue, ...]
    blank_lines: int


@dataclass(frozen=True)
class ImportReport:
    """Dry-run or persisted import outcome."""

    files: int
    valid_records: int
    imported: int
    skipped: int
    blank_lines: int
    issues: tuple[ImportIssue, ...]
    dry_run: bool

    @property
    def ok(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "valid_records": self.valid_records,
            "imported": self.imported,
            "skipped": self.skipped,
            "blank_lines": self.blank_lines,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ExportResult:
    """Canonical export output."""

    count: int
    lines: tuple[str, ...]
    path: Path | None = None


class JsonlImporter:
    """Validate JSONL without storage or persist valid files atomically."""

    def __init__(
        self,
        repository: ImportRepository | None = None,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def run(self, source: str | Path, *, dry_run: bool = False) -> ImportReport:
        plans = plan_jsonl(source, clock=self._clock)
        imported = 0
        skipped = 0
        if not dry_run:
            if self._repository is None:
                raise ImportFailureError("A repository is required for a real import.")
            for plan in plans:
                if plan.issues:
                    continue
                stored = self._repository.import_records(plan.records)
                imported += stored.imported
                skipped += stored.skipped
        issues = tuple(issue for plan in plans for issue in plan.issues)
        return ImportReport(
            files=len(plans),
            valid_records=sum(len(plan.records) for plan in plans if not plan.issues),
            imported=imported,
            skipped=skipped,
            blank_lines=sum(plan.blank_lines for plan in plans),
            issues=issues,
            dry_run=dry_run,
        )


def plan_jsonl(
    source: str | Path, *, clock: Clock = _utc_now
) -> tuple[ImportFilePlan, ...]:
    """Read and normalize all JSONL sources without touching a database."""
    path = Path(source).expanduser().resolve()
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(
            candidate for candidate in path.rglob("*.jsonl") if candidate.is_file()
        )
    else:
        raise ImportFailureError(f"JSONL source does not exist: {path}")
    if not files:
        raise ImportFailureError(f"No JSONL files found under {path}")
    imported_at = clock().astimezone(UTC)
    return tuple(_plan_file(file_path, imported_at) for file_path in files)


def _plan_file(path: Path, imported_at: datetime) -> ImportFilePlan:
    records: list[ImportRecord] = []
    issues: list[ImportIssue] = []
    blank_lines = 0
    occurrences: Counter[str] = Counter()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return ImportFilePlan(
            path=path,
            records=(),
            issues=(ImportIssue(path, None, str(error)),),
            blank_lines=0,
        )

    for line_number, raw_line in enumerate(lines, 1):
        if not raw_line.strip():
            blank_lines += 1
            continue
        try:
            payload = json.loads(raw_line)
            if not isinstance(payload, dict):
                raise ValueError("each JSONL line must contain an object")
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            occurrences[canonical] += 1
            fingerprint = hashlib.sha256(
                f"friction-import-v1\0{canonical}\0{occurrences[canonical]}".encode()
            ).hexdigest()
            raw_sha256 = hashlib.sha256(raw_line.encode()).hexdigest()
            item, event, source_format = _normalize_record(
                payload, path=path, imported_at=imported_at
            )
            records.append(
                ImportRecord(
                    item=item,
                    event=event,
                    provenance=ImportProvenance(
                        source_path=path,
                        source_line=line_number,
                        source_format=source_format,
                        fingerprint=fingerprint,
                        raw_sha256=raw_sha256,
                        imported_at=imported_at,
                    ),
                )
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            issues.append(ImportIssue(path, line_number, str(error)))
    return ImportFilePlan(
        path=path,
        records=tuple(records),
        issues=tuple(issues),
        blank_lines=blank_lines,
    )


def _normalize_record(
    payload: dict[str, Any], *, path: Path, imported_at: datetime
) -> tuple[FrictionItem, FrictionEvent, str]:
    if payload.get("schema_version") == 1:
        return _normalize_canonical(payload)
    return _normalize_legacy(payload, path=path, imported_at=imported_at)


def _normalize_canonical(
    payload: dict[str, Any],
) -> tuple[FrictionItem, FrictionEvent, str]:
    if payload.get("record_type") != "friction_item":
        raise ValueError("canonical v1 record_type must be 'friction_item'")
    data = ItemData.model_validate(payload.get("data"))
    item = FrictionItem.model_validate(data.model_dump())
    event = FrictionEvent(
        item_id=item.id,
        event_type=EventType.CREATED,
        occurred_at=item.created_at,
        to_revision=item.revision,
        payload={"source": item.source.value, "canonical_import": True},
    )
    return item, event, "canonical_v1"


def _normalize_legacy(
    payload: dict[str, Any], *, path: Path, imported_at: datetime
) -> tuple[FrictionItem, FrictionEvent, str]:
    note = payload.get("note")
    timestamp_text = payload.get("timestamp")
    if not isinstance(note, str):
        raise ValueError("legacy note must be a string")
    if not isinstance(timestamp_text, str):
        raise ValueError("legacy timestamp must be a string")
    created_at = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("legacy timestamp must include a UTC offset")

    source = ItemSource(payload.get("source") or "import")
    source_format = f"legacy_{source.value}"
    raw_status = payload.get("status") or "wip"
    status_map = {
        "wip": ItemStatus.OPEN,
        "open": ItemStatus.OPEN,
        "done": ItemStatus.DONE,
        "dismissed": ItemStatus.DISMISSED,
    }
    if raw_status not in status_map:
        raise ValueError(f"unsupported legacy status: {raw_status!r}")

    legacy_path = _optional_string(payload.get("path"))
    if source is ItemSource.CLI:
        item_path = None
        cwd = legacy_path
    else:
        item_path = legacy_path
        cwd = str(Path(legacy_path).parent) if legacy_path else None
    raw_repo = _optional_string(payload.get("git_repo") or payload.get("git-repo"))
    git_root = raw_repo if raw_repo and Path(raw_repo).is_absolute() else None
    git_repo = Path(raw_repo).name if raw_repo else None
    filetype = _optional_string(payload.get("filetype") or payload.get("major-mode"))
    git_branch = _optional_string(
        payload.get("git_branch") or payload.get("git-branch")
    )
    archived_at = imported_at if path.parent.name == "archive" else None
    item = FrictionItem(
        id=uuid4(),
        note=note,
        status=status_map[raw_status],
        created_at=created_at,
        updated_at=created_at,
        archived_at=archived_at,
        source=source,
        path=item_path,
        line=payload.get("line"),
        column=payload.get("column"),
        cwd=cwd,
        filetype=filetype,
        git_root=git_root,
        git_repo=git_repo,
        git_branch=git_branch,
        metadata={
            "legacy": {
                "source_format": source_format,
                "timestamp": timestamp_text,
                "status": str(raw_status),
            }
        },
        revision=1,
    )
    event = FrictionEvent(
        item_id=item.id,
        event_type=EventType.CREATED,
        occurred_at=item.created_at,
        to_revision=1,
        payload={"source": item.source.value, "legacy_import": True},
    )
    return item, event, source_format


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("legacy optional text fields must be strings or null")
    stripped = value.strip()
    return stripped or None


def canonical_jsonl(
    service: FrictionService,
    *,
    statuses: tuple[ItemStatus, ...] = (),
    sources: tuple[ItemSource, ...] = (),
    tags: tuple[str, ...] = (),
) -> ExportResult:
    """Render all matching items as canonical JSONL v1."""
    items: list[FrictionItem] = []
    offset = 0
    while True:
        page = service.list(
            ItemQuery(
                statuses=statuses,
                sources=sources,
                tags=tags,
                archive=ArchiveFilter.ALL,
                limit=1000,
                offset=offset,
            )
        )
        items.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)
    lines = tuple(
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "friction_item",
                "data": ItemData.from_domain(item).model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in items
    )
    return ExportResult(count=len(lines), lines=lines)


def write_jsonl_export(
    result: ExportResult,
    output: str | Path,
    *,
    force: bool = False,
    clock: Clock = _utc_now,
) -> ExportResult:
    """Atomically write canonical JSONL to a file or timestamped directory."""
    requested = Path(output).expanduser()
    if (requested.exists() and requested.is_dir()) or not requested.suffix:
        requested.mkdir(parents=True, exist_ok=True)
        timestamp = clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = requested / f"friction-v1-{timestamp}.jsonl"
    else:
        destination = requested
        destination.parent.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    if destination.exists() and not force:
        raise StorageError(f"Export already exists: {destination}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for line in result.lines:
                temporary.write(line)
                temporary.write("\n")
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return ExportResult(count=result.count, lines=result.lines, path=destination)
