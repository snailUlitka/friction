"""Use cases for creating, querying, and mutating friction items."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from friction.application.ports import ItemQuery, ItemRepository
from friction.domain.errors import RevisionConflictError
from friction.domain.models import (
    CreateItem,
    EventType,
    FrictionEvent,
    FrictionItem,
    ItemPatch,
)
from friction.domain.statuses import ItemStatus, validate_transition

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _event_value(value: Any) -> Any:
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


class FrictionService:
    """Public application API shared by all adapters."""

    def __init__(self, repository: ItemRepository, *, clock: Clock = _default_clock):
        self._repository = repository
        self._clock = clock

    def create(self, command: CreateItem) -> FrictionItem:
        """Create and persist an open item."""
        item = command.to_item()
        event = FrictionEvent(
            item_id=item.id,
            event_type=EventType.CREATED,
            occurred_at=item.created_at,
            to_revision=item.revision,
            payload={"source": item.source.value},
        )
        self._repository.add(item, event)
        return item

    def get(self, identifier: str | UUID) -> FrictionItem:
        """Get one item by UUID or unique prefix."""
        return self._repository.get(identifier)

    def list(self, query: ItemQuery | None = None) -> builtins.list[FrictionItem]:
        """List matching items."""
        return self._repository.list(query or ItemQuery())

    def search(
        self, text: str, query: ItemQuery | None = None
    ) -> builtins.list[FrictionItem]:
        """Search item content and context."""
        query_text = text.strip()
        if not query_text:
            return []
        return self._repository.search(query_text, query or ItemQuery())

    def events(self, identifier: str | UUID) -> builtins.list[FrictionEvent]:
        """Return the complete event history for one item."""
        return self._repository.events(identifier)

    def update(
        self,
        identifier: str | UUID,
        patch: ItemPatch,
        *,
        expected_revision: int,
    ) -> FrictionItem:
        """Update non-lifecycle fields using optimistic concurrency."""
        current = self._checked_current(identifier, expected_revision)
        changes = patch.changes()
        actual_changes = {
            key: value
            for key, value in changes.items()
            if getattr(current, key) != value
        }
        if not actual_changes:
            return current

        updated = current.model_copy(
            update={
                **actual_changes,
                "updated_at": self._clock(),
                "revision": current.revision + 1,
            }
        )
        payload = {
            key: {
                "from": _event_value(getattr(current, key)),
                "to": _event_value(value),
            }
            for key, value in actual_changes.items()
        }
        event = self._event(current, updated, EventType.UPDATED, payload)
        self._repository.update(updated, event, expected_revision=expected_revision)
        return updated

    def mark_done(
        self, identifier: str | UUID, *, expected_revision: int
    ) -> FrictionItem:
        """Move an open item to done."""
        return self._change_status(identifier, ItemStatus.DONE, expected_revision)

    def dismiss(
        self, identifier: str | UUID, *, expected_revision: int
    ) -> FrictionItem:
        """Move an open item to dismissed."""
        return self._change_status(identifier, ItemStatus.DISMISSED, expected_revision)

    def reopen(
        self, identifier: str | UUID, *, expected_revision: int
    ) -> FrictionItem:
        """Move a done or dismissed item back to open."""
        return self._change_status(identifier, ItemStatus.OPEN, expected_revision)

    def archive(
        self, identifier: str | UUID, *, expected_revision: int
    ) -> FrictionItem:
        """Archive an item without changing its status."""
        current = self._checked_current(identifier, expected_revision)
        if current.archived_at is not None:
            return current
        changed_at = self._clock()
        updated = current.model_copy(
            update={
                "archived_at": changed_at,
                "updated_at": changed_at,
                "revision": current.revision + 1,
            }
        )
        event = self._event(current, updated, EventType.ARCHIVED)
        self._repository.update(updated, event, expected_revision=expected_revision)
        return updated

    def unarchive(
        self, identifier: str | UUID, *, expected_revision: int
    ) -> FrictionItem:
        """Restore an archived item without changing its status."""
        current = self._checked_current(identifier, expected_revision)
        if current.archived_at is None:
            return current
        updated = current.model_copy(
            update={
                "archived_at": None,
                "updated_at": self._clock(),
                "revision": current.revision + 1,
            }
        )
        event = self._event(current, updated, EventType.UNARCHIVED)
        self._repository.update(updated, event, expected_revision=expected_revision)
        return updated

    def _change_status(
        self,
        identifier: str | UUID,
        target: ItemStatus,
        expected_revision: int,
    ) -> FrictionItem:
        current = self._checked_current(identifier, expected_revision)
        if not validate_transition(current.status, target):
            return current
        updated = current.model_copy(
            update={
                "status": target,
                "updated_at": self._clock(),
                "revision": current.revision + 1,
            }
        )
        event = self._event(
            current,
            updated,
            EventType.STATUS_CHANGED,
            {"from": current.status.value, "to": target.value},
        )
        self._repository.update(updated, event, expected_revision=expected_revision)
        return updated

    def _checked_current(
        self, identifier: str | UUID, expected_revision: int
    ) -> FrictionItem:
        current = self._repository.get(identifier)
        if current.revision != expected_revision:
            raise RevisionConflictError(
                str(current.id), expected_revision, current.revision
            )
        return current

    def _event(
        self,
        current: FrictionItem,
        updated: FrictionItem,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> FrictionEvent:
        return FrictionEvent(
            item_id=current.id,
            event_type=event_type,
            occurred_at=updated.updated_at,
            from_revision=current.revision,
            to_revision=updated.revision,
            payload=payload or {},
        )
