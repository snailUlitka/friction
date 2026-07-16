from __future__ import annotations

import builtins
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from friction.application import FrictionService, ItemQuery
from friction.domain import (
    CreateItem,
    FrictionEvent,
    FrictionItem,
    ItemNotFoundError,
    ItemPatch,
    ItemStatus,
    RevisionConflictError,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, FrictionItem] = {}
        self.history: dict[UUID, list[FrictionEvent]] = {}

    def add(self, item: FrictionItem, event: FrictionEvent) -> None:
        self.items[item.id] = item
        self.history[item.id] = [event]

    def get(self, identifier: str | UUID) -> FrictionItem:
        text = str(identifier)
        matches = [
            item for item in self.items.values() if str(item.id).startswith(text)
        ]
        if len(matches) != 1:
            raise ItemNotFoundError(text)
        return matches[0]

    def list(self, query: ItemQuery) -> builtins.list[FrictionItem]:
        return list(self.items.values())[query.offset : query.offset + query.limit]

    def search(
        self, text: str, query: ItemQuery
    ) -> builtins.list[FrictionItem]:
        return [
            item
            for item in self.list(query)
            if text.casefold() in item.note.casefold()
        ]

    def update(
        self,
        item: FrictionItem,
        event: FrictionEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self.items[item.id]
        if current.revision != expected_revision:
            raise RevisionConflictError(
                str(item.id), expected_revision, current.revision
            )
        self.items[item.id] = item
        self.history[item.id].append(event)

    def events(self, identifier: str | UUID) -> builtins.list[FrictionEvent]:
        item = self.get(identifier)
        return self.history[item.id]


@pytest.fixture
def clock() -> datetime:
    return datetime(2026, 7, 16, 12, tzinfo=UTC)


@pytest.fixture
def repository() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def service(repository: MemoryRepository, clock: datetime) -> FrictionService:
    return FrictionService(repository, clock=lambda: clock)


def test_service_creates_updates_and_audits(
    service: FrictionService, clock: datetime
) -> None:
    item = service.create(
        CreateItem(note="clipboard is slow", created_at=clock - timedelta(minutes=1))
    )

    updated = service.update(
        item.id,
        ItemPatch(note="clipboard loses formatting", tags=("editor",)),
        expected_revision=1,
    )

    assert updated.note == "clipboard loses formatting"
    assert updated.revision == 2
    assert len(service.events(item.id)) == 2


def test_service_enforces_revision_and_status_transitions(
    service: FrictionService, clock: datetime
) -> None:
    item = service.create(CreateItem(note="slow command", created_at=clock))
    done = service.mark_done(item.id, expected_revision=1)

    with pytest.raises(RevisionConflictError):
        service.reopen(item.id, expected_revision=1)

    reopened = service.reopen(done.id, expected_revision=2)
    assert reopened.status is ItemStatus.OPEN
    assert reopened.revision == 3


def test_archive_is_reversible_and_independent_of_status(
    service: FrictionService, clock: datetime
) -> None:
    item = service.create(CreateItem(note="archive me", created_at=clock))
    archived = service.archive(item.id, expected_revision=1)
    restored = service.unarchive(archived.id, expected_revision=2)

    assert archived.archived_at == clock
    assert archived.status is ItemStatus.OPEN
    assert restored.archived_at is None
    assert restored.revision == 3


def test_noop_does_not_increment_revision(
    service: FrictionService, clock: datetime
) -> None:
    item = service.create(CreateItem(note="same", created_at=clock))

    same = service.update(item.id, ItemPatch(note="same"), expected_revision=1)

    assert same.revision == 1
    assert len(service.events(item.id)) == 1
