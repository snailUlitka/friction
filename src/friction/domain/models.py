"""Domain data structures."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

from friction.domain.statuses import ItemStatus

PositiveInt = Annotated[int, Field(gt=0)]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = raw_tag.strip()
        if not tag:
            raise ValueError("tags must not be empty")
        key = tag.casefold()
        if key not in seen:
            normalized.append(tag)
            seen.add(key)
    return tuple(sorted(normalized, key=str.casefold))


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ItemSource(StrEnum):
    """Known capture source."""

    CLI = "cli"
    EMACS = "emacs"
    NVIM = "nvim"
    MCP = "mcp"
    WEB = "web"
    IMPORT = "import"


class EventType(StrEnum):
    """Audited mutations."""

    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    ARCHIVED = "archived"
    UNARCHIVED = "unarchived"


class DomainModel(BaseModel):
    """Shared strict immutable model configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FrictionItem(DomainModel):
    """Complete friction item state."""

    id: UUID
    note: str
    status: ItemStatus = ItemStatus.OPEN
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    source: ItemSource
    path: str | None = None
    line: PositiveInt | None = None
    column: PositiveInt | None = None
    cwd: str | None = None
    filetype: str | None = None
    git_root: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    revision: Annotated[int, Field(gt=0)] = 1

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        note = value.strip()
        if not note:
            raise ValueError("note must not be empty")
        return note

    @field_validator(
        "path",
        "cwd",
        "filetype",
        "git_root",
        "git_repo",
        "git_branch",
        "git_commit",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        return _normalize_optional_string(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_tags(value)

    @field_validator("created_at", "updated_at", "archived_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class CreateItem(DomainModel):
    """Input for creating an item."""

    id: UUID = Field(default_factory=uuid4)
    note: str
    source: ItemSource = ItemSource.CLI
    created_at: datetime = Field(default_factory=utc_now)
    path: str | None = None
    line: PositiveInt | None = None
    column: PositiveInt | None = None
    cwd: str | None = None
    filetype: str | None = None
    git_root: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        note = value.strip()
        if not note:
            raise ValueError("note must not be empty")
        return note

    @field_validator(
        "path",
        "cwd",
        "filetype",
        "git_root",
        "git_repo",
        "git_branch",
        "git_commit",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        return _normalize_optional_string(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_tags(value)

    @field_validator("created_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    def to_item(self) -> FrictionItem:
        """Create the initial persisted state."""
        values = self.model_dump()
        created_at = values.pop("created_at")
        return FrictionItem(
            **values,
            status=ItemStatus.OPEN,
            created_at=created_at,
            updated_at=created_at,
            revision=1,
        )


class ItemPatch(DomainModel):
    """Patchable non-lifecycle item fields."""

    note: str | None = None
    path: str | None = None
    line: PositiveInt | None = None
    column: PositiveInt | None = None
    cwd: str | None = None
    filetype: str | None = None
    git_root: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: tuple[str, ...] | None = None
    metadata: dict[str, JsonValue] | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        note = value.strip()
        if not note:
            raise ValueError("note must not be empty")
        return note

    @field_validator(
        "path",
        "cwd",
        "filetype",
        "git_root",
        "git_repo",
        "git_branch",
        "git_commit",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        return _normalize_optional_string(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else _normalize_tags(value)

    def changes(self) -> dict[str, Any]:
        """Return only explicitly supplied fields."""
        return {
            name: getattr(self, name)
            for name in self.model_fields_set
            if name in type(self).model_fields
        }


class FrictionEvent(DomainModel):
    """Immutable audit event for an item mutation."""

    id: UUID = Field(default_factory=uuid4)
    item_id: UUID
    event_type: EventType
    occurred_at: datetime = Field(default_factory=utc_now)
    from_revision: int | None = None
    to_revision: Annotated[int, Field(gt=0)]
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)
