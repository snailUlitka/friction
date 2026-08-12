"""SQLite engine and SQLAlchemy repository implementation."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Engine,
    Select,
    create_engine,
    delete,
    event,
    select,
    text,
    update,
)
from sqlalchemy.engine import URL, CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from friction.application.imports import ImportRecord, StoredImportResult
from friction.application.ports import ArchiveFilter, ItemQuery
from friction.domain.errors import (
    AmbiguousIdentifierError,
    DuplicateItemError,
    ImportFailureError,
    ItemNotFoundError,
    RevisionConflictError,
    StorageError,
)
from friction.domain.models import (
    EventType,
    FrictionEvent,
    FrictionItem,
    ItemSource,
)
from friction.domain.statuses import ItemStatus
from friction.storage.orm import (
    EventRow,
    FrictionItemRow,
    ImportRow,
    TagRow,
    item_tags,
    tag_names,
)

DATABASE_ENVIRONMENT_VARIABLE = "FRICTION_DB_PATH"
BUSY_TIMEOUT_MS = 5_000


def default_database_path() -> Path:
    """Return the default macOS application data path."""
    return Path.home() / "Library" / "Application Support" / "friction" / "friction.db"


def resolve_database_path(
    explicit: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve explicit, environment, and default database path precedence."""
    environ = os.environ if environment is None else environment
    raw_path = explicit or environ.get(DATABASE_ENVIRONMENT_VARIABLE)
    path = Path(raw_path).expanduser() if raw_path else default_database_path()
    return path.resolve()


def create_sqlite_engine(path: str | Path, *, create_parent: bool = True) -> Engine:
    """Create a configured SQLite engine for one database path."""
    database_path = Path(path).expanduser().resolve()
    if create_parent:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    url = URL.create("sqlite+pysqlite", database=str(database_path))
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine


def _serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _required_timestamp(value: datetime) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        raise StorageError("Required timestamp is missing.")
    return timestamp


def _item_values(item: FrictionItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "note": item.note,
        "status": item.status.value,
        "created_at": _required_timestamp(item.created_at),
        "updated_at": _required_timestamp(item.updated_at),
        "archived_at": _timestamp(item.archived_at),
        "source": item.source.value,
        "path": item.path,
        "line": item.line,
        "column": item.column,
        "cwd": item.cwd,
        "filetype": item.filetype,
        "git_root": item.git_root,
        "git_repo": item.git_repo,
        "git_branch": item.git_branch,
        "git_commit": item.git_commit,
        "metadata_json": _serialize_json(item.metadata),
        "revision": item.revision,
    }


def _event_row(event_value: FrictionEvent) -> EventRow:
    return EventRow(
        id=str(event_value.id),
        item_id=str(event_value.item_id),
        event_type=event_value.event_type.value,
        occurred_at=_required_timestamp(event_value.occurred_at),
        from_revision=event_value.from_revision,
        to_revision=event_value.to_revision,
        payload_json=_serialize_json(event_value.payload),
    )


def _domain_item(row: FrictionItemRow) -> FrictionItem:
    created_at = _parse_timestamp(row.created_at)
    updated_at = _parse_timestamp(row.updated_at)
    if created_at is None or updated_at is None:
        raise StorageError("Stored item is missing required timestamps.")
    return FrictionItem(
        id=UUID(row.id),
        note=row.note,
        status=ItemStatus(row.status),
        created_at=created_at,
        updated_at=updated_at,
        archived_at=_parse_timestamp(row.archived_at),
        source=ItemSource(row.source),
        path=row.path,
        line=row.line,
        column=row.column,
        cwd=row.cwd,
        filetype=row.filetype,
        git_root=row.git_root,
        git_repo=row.git_repo,
        git_branch=row.git_branch,
        git_commit=row.git_commit,
        tags=tag_names(row.tags),
        metadata=json.loads(row.metadata_json),
        revision=row.revision,
    )


def _domain_event(row: EventRow) -> FrictionEvent:
    occurred_at = _parse_timestamp(row.occurred_at)
    if occurred_at is None:
        raise StorageError("Stored event is missing its timestamp.")
    return FrictionEvent(
        id=UUID(row.id),
        item_id=UUID(row.item_id),
        event_type=EventType(row.event_type),
        occurred_at=occurred_at,
        from_revision=row.from_revision,
        to_revision=row.to_revision,
        payload=json.loads(row.payload_json),
    )


class SQLiteItemRepository:
    """SQLAlchemy implementation of the application repository port."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def add(self, item: FrictionItem, event_value: FrictionEvent) -> None:
        try:
            with self._sessions.begin() as session:
                row = FrictionItemRow(**_item_values(item))
                row.tags = self._tags(session, item.tags)
                session.add(row)
                session.flush()
                session.add(_event_row(event_value))
                session.flush()
                self._sync_fts(session, item)
        except IntegrityError as error:
            raise DuplicateItemError(
                f"Friction item {item.id} already exists.",
                details={"item_id": str(item.id)},
            ) from error

    def get(self, identifier: str | UUID) -> FrictionItem:
        with self._sessions() as session:
            row = self._resolve_row(session, identifier)
            return _domain_item(row)

    def list(self, query: ItemQuery) -> builtins.list[FrictionItem]:
        with self._sessions() as session:
            statement = self._filtered_statement(query)
            statement = statement.order_by(
                FrictionItemRow.created_at.desc(), FrictionItemRow.id.desc()
            )
            statement = statement.offset(query.offset).limit(query.limit)
            rows = session.scalars(statement).unique().all()
            return [_domain_item(row) for row in rows]

    def search(
        self, text_value: str, query: ItemQuery
    ) -> builtins.list[FrictionItem]:
        fts_query = self._fts_query(text_value)
        if not fts_query:
            return []
        with self._sessions() as session:
            identifiers = session.execute(
                text(
                    "SELECT item_id FROM friction_items_fts "
                    "WHERE friction_items_fts MATCH :query "
                    "ORDER BY bm25(friction_items_fts), item_id ASC LIMIT 1000"
                ),
                {"query": fts_query},
            ).scalars()
            ranking = list(identifiers)
            if not ranking:
                return []
            statement = self._filtered_statement(query).where(
                FrictionItemRow.id.in_(ranking)
            )
            rows = session.scalars(statement).unique().all()
            by_id = {row.id: _domain_item(row) for row in rows}
            ordered = [by_id[item_id] for item_id in ranking if item_id in by_id]
            return ordered[query.offset : query.offset + query.limit]

    def update(
        self,
        item: FrictionItem,
        event_value: FrictionEvent,
        *,
        expected_revision: int,
    ) -> None:
        values = _item_values(item)
        values.pop("id")
        with self._sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(FrictionItemRow)
                    .where(
                        FrictionItemRow.id == str(item.id),
                        FrictionItemRow.revision == expected_revision,
                    )
                    .values(**values)
                ),
            )
            if result.rowcount != 1:
                actual = session.scalar(
                    select(FrictionItemRow.revision).where(
                        FrictionItemRow.id == str(item.id)
                    )
                )
                if actual is None:
                    raise ItemNotFoundError(str(item.id))
                raise RevisionConflictError(str(item.id), expected_revision, actual)
            session.execute(
                delete(item_tags).where(item_tags.c.item_id == str(item.id))
            )
            for tag in self._tags(session, item.tags):
                session.execute(
                    item_tags.insert().values(item_id=str(item.id), tag_id=tag.id)
                )
            session.add(_event_row(event_value))
            self._sync_fts(session, item)

    def events(self, identifier: str | UUID) -> builtins.list[FrictionEvent]:
        with self._sessions() as session:
            item = self._resolve_row(session, identifier)
            statement = (
                select(EventRow)
                .where(EventRow.item_id == item.id)
                .order_by(EventRow.occurred_at, EventRow.id)
            )
            return [_domain_event(row) for row in session.scalars(statement)]

    def import_records(
        self, records: tuple[ImportRecord, ...]
    ) -> StoredImportResult:
        """Persist one validated JSONL file in a single transaction."""
        if not records:
            return StoredImportResult(imported=0, skipped=0)
        fingerprints = [record.provenance.fingerprint for record in records]
        try:
            with self._sessions.begin() as session:
                existing = set(
                    session.scalars(
                        select(ImportRow.fingerprint).where(
                            ImportRow.fingerprint.in_(fingerprints)
                        )
                    )
                )
                imported = 0
                for record in records:
                    if record.provenance.fingerprint in existing:
                        continue
                    row = FrictionItemRow(**_item_values(record.item))
                    row.tags = self._tags(session, record.item.tags)
                    session.add(row)
                    session.flush()
                    session.add(_event_row(record.event))
                    session.add(
                        ImportRow(
                            id=str(uuid4()),
                            item_id=str(record.item.id),
                            source_path=str(record.provenance.source_path),
                            source_line=record.provenance.source_line,
                            source_format=record.provenance.source_format,
                            fingerprint=record.provenance.fingerprint,
                            raw_sha256=record.provenance.raw_sha256,
                            imported_at=_required_timestamp(
                                record.provenance.imported_at
                            ),
                        )
                    )
                    self._sync_fts(session, record.item)
                    imported += 1
                return StoredImportResult(
                    imported=imported, skipped=len(records) - imported
                )
        except IntegrityError as error:
            raise ImportFailureError(
                "Import conflicts with an existing item or provenance record."
            ) from error

    def _resolve_row(self, session: Session, identifier: str | UUID) -> FrictionItemRow:
        text_identifier = str(identifier).strip().lower()
        if not text_identifier:
            raise ItemNotFoundError(text_identifier)
        statement = (
            select(FrictionItemRow)
            .options(selectinload(FrictionItemRow.tags))
            .where(FrictionItemRow.id.like(f"{text_identifier}%"))
            .limit(2)
        )
        rows = list(session.scalars(statement).unique())
        if not rows:
            raise ItemNotFoundError(text_identifier)
        if len(rows) > 1:
            raise AmbiguousIdentifierError(text_identifier)
        return rows[0]

    def _filtered_statement(self, query: ItemQuery) -> Select[tuple[FrictionItemRow]]:
        statement = select(FrictionItemRow).options(selectinload(FrictionItemRow.tags))
        if query.statuses:
            statement = statement.where(
                FrictionItemRow.status.in_([status.value for status in query.statuses])
            )
        if query.sources:
            statement = statement.where(
                FrictionItemRow.source.in_([source.value for source in query.sources])
            )
        if query.repo:
            statement = statement.where(FrictionItemRow.git_repo == query.repo)
        if query.archive is ArchiveFilter.ACTIVE:
            statement = statement.where(FrictionItemRow.archived_at.is_(None))
        elif query.archive is ArchiveFilter.ARCHIVED:
            statement = statement.where(FrictionItemRow.archived_at.is_not(None))
        for tag in query.tags:
            normalized = tag.strip().casefold()
            statement = statement.where(
                FrictionItemRow.tags.any(TagRow.normalized_name == normalized)
            )
        return statement

    def _tags(
        self, session: Session, names: tuple[str, ...]
    ) -> builtins.list[TagRow]:
        rows: builtins.list[TagRow] = []
        for name in names:
            normalized = name.casefold()
            row = session.scalar(
                select(TagRow).where(TagRow.normalized_name == normalized)
            )
            if row is None:
                row = TagRow(name=name, normalized_name=normalized)
                session.add(row)
                session.flush()
            rows.append(row)
        return rows

    def _sync_fts(self, session: Session, item: FrictionItem) -> None:
        session.execute(
            text("DELETE FROM friction_items_fts WHERE item_id = :item_id"),
            {"item_id": str(item.id)},
        )
        session.execute(
            text(
                "INSERT INTO friction_items_fts "
                "(item_id, note, tags, path, cwd, git_repo) "
                "VALUES (:item_id, :note, :tags, :path, :cwd, :git_repo)"
            ),
            {
                "item_id": str(item.id),
                "note": item.note,
                "tags": " ".join(item.tags),
                "path": item.path or "",
                "cwd": item.cwd or "",
                "git_repo": item.git_repo or "",
            },
        )

    @staticmethod
    def _fts_query(value: str) -> str:
        terms = re.findall(r"\w+", value, flags=re.UNICODE)
        return " AND ".join(f'"{term}"*' for term in terms)


def database_sha256(path: Path) -> str:
    """Return a file digest used by backup verification."""
    digest = hashlib.sha256()
    with path.open("rb") as database:
        for chunk in iter(lambda: database.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
