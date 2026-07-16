from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from friction.application import ArchiveFilter, FrictionService, ItemQuery
from friction.domain import (
    CreateItem,
    DuplicateItemError,
    ItemPatch,
    ItemSource,
    RevisionConflictError,
)
from friction.storage import (
    SQLiteItemRepository,
    create_sqlite_engine,
    upgrade_database,
)


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteItemRepository:
    engine = create_sqlite_engine(tmp_path / "friction.db")
    upgrade_database(engine)
    return SQLiteItemRepository(engine)


@pytest.fixture
def service(repository: SQLiteItemRepository) -> FrictionService:
    moment = datetime(2026, 7, 16, 12, tzinfo=UTC)
    return FrictionService(repository, clock=lambda: moment)


def test_sqlite_pragmas_are_configured(repository: SQLiteItemRepository) -> None:
    with repository.engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert busy_timeout == 5_000


def test_repository_round_trip_filters_and_search(
    service: FrictionService, repository: SQLiteItemRepository
) -> None:
    created = service.create(
        CreateItem(
            note="Clipboard formatting is slow",
            source=ItemSource.NVIM,
            cwd="/tmp/project",
            git_repo="configs",
            tags=("Editor", "clipboard"),
        )
    )
    service.create(CreateItem(note="Unrelated terminal issue", tags=("shell",)))

    loaded = service.get(str(created.id)[:8])
    filtered = service.list(ItemQuery(repo="configs", tags=("editor",)))
    searched = service.search("clipboard slow", ItemQuery())

    assert loaded == created
    assert filtered == [created]
    assert searched == [created]
    assert len(repository.events(created.id)) == 1


def test_repository_archive_visibility_and_cas(service: FrictionService) -> None:
    item = service.create(CreateItem(note="archive and protect"))
    archived = service.archive(item.id, expected_revision=1)

    assert service.list() == []
    assert service.list(ItemQuery(archive=ArchiveFilter.ARCHIVED)) == [archived]

    with pytest.raises(RevisionConflictError):
        service.update(
            item.id,
            ItemPatch(note="stale overwrite"),
            expected_revision=1,
        )


def test_duplicate_uuid_is_rejected(service: FrictionService) -> None:
    command = CreateItem(note="same uuid")
    service.create(command)

    with pytest.raises(DuplicateItemError):
        service.create(command)
