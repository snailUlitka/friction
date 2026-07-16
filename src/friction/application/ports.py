"""Ports implemented by persistence adapters."""

from __future__ import annotations

import builtins
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from friction.domain.models import FrictionEvent, FrictionItem, ItemSource
from friction.domain.statuses import ItemStatus


class ArchiveFilter(StrEnum):
    """Archive visibility for list and search queries."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


class ItemQuery(BaseModel):
    """Stable filters shared by list and search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statuses: tuple[ItemStatus, ...] = ()
    sources: tuple[ItemSource, ...] = ()
    repo: str | None = None
    tags: tuple[str, ...] = ()
    archive: ArchiveFilter = ArchiveFilter.ACTIVE
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class ItemRepository(Protocol):
    """Persistence boundary required by the application service."""

    def add(self, item: FrictionItem, event: FrictionEvent) -> None:
        """Persist a new item and its creation event atomically."""

    def get(self, identifier: str | UUID) -> FrictionItem:
        """Resolve a full UUID or unique UUID prefix."""

    def list(self, query: ItemQuery) -> builtins.list[FrictionItem]:
        """List matching items in descending creation order."""

    def search(self, text: str, query: ItemQuery) -> builtins.list[FrictionItem]:
        """Full-text search matching items."""

    def update(
        self,
        item: FrictionItem,
        event: FrictionEvent,
        *,
        expected_revision: int,
    ) -> None:
        """Persist a compare-and-swap update and event atomically."""

    def events(self, identifier: str | UUID) -> builtins.list[FrictionEvent]:
        """Return item events in chronological order."""
