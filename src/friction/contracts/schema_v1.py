"""JSON contract version 1."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from friction.domain.models import (
    CreateItem,
    FrictionItem,
    ItemPatch,
    ItemSource,
)
from friction.domain.statuses import ItemStatus


class ContractModel(BaseModel):
    """Strict base for versioned wire models."""

    model_config = ConfigDict(extra="forbid")


class ApiError(ContractModel):
    """Stable error payload."""

    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ApiEnvelope[T](ContractModel):
    """Versioned JSON response envelope."""

    schema_version: Literal[1] = 1
    data: T | None = None
    error: ApiError | None = None

    @model_validator(mode="after")
    def exactly_one_result(self) -> ApiEnvelope[T]:
        if (self.data is None) == (self.error is None):
            raise ValueError("exactly one of data or error must be set")
        return self


class AddData(ContractModel):
    """Machine input for item capture."""

    note: str
    source: ItemSource = ItemSource.CLI
    path: str | None = None
    line: int | None = Field(default=None, gt=0)
    column: int | None = Field(default=None, gt=0)
    cwd: str | None = None
    filetype: str | None = None
    git_root: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    def to_command(self) -> CreateItem:
        """Convert the wire request into a domain command."""
        return CreateItem.model_validate(self.model_dump())


class AddRequest(ContractModel):
    """Versioned add request."""

    schema_version: Literal[1]
    data: AddData


class UpdateData(ContractModel):
    """Machine input for optimistic item updates."""

    revision: int = Field(gt=0)
    note: str | None = None
    path: str | None = None
    line: int | None = Field(default=None, gt=0)
    column: int | None = Field(default=None, gt=0)
    cwd: str | None = None
    filetype: str | None = None
    git_root: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    tags: tuple[str, ...] | None = None
    metadata: dict[str, JsonValue] | None = None

    def to_patch(self) -> ItemPatch:
        """Convert explicitly supplied fields into a domain patch."""
        values = self.model_dump(exclude={"revision"}, exclude_unset=True)
        return ItemPatch.model_validate(values)


class UpdateRequest(ContractModel):
    """Versioned update request."""

    schema_version: Literal[1]
    data: UpdateData


class ItemData(ContractModel):
    """Canonical item representation."""

    id: UUID
    note: str
    status: ItemStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    source: ItemSource
    path: str | None
    line: int | None
    column: int | None
    cwd: str | None
    filetype: str | None
    git_root: str | None
    git_repo: str | None
    git_branch: str | None
    git_commit: str | None
    tags: tuple[str, ...]
    metadata: dict[str, JsonValue]
    revision: int

    @classmethod
    def from_domain(cls, item: FrictionItem) -> ItemData:
        """Create a wire item from domain state."""
        return cls.model_validate(item.model_dump())


class ItemListData(ContractModel):
    """Collection response."""

    items: list[ItemData]
    count: int

    @classmethod
    def from_domain(cls, items: list[FrictionItem]) -> ItemListData:
        """Create a collection payload."""
        return cls(
            items=[ItemData.from_domain(item) for item in items], count=len(items)
        )


def success_envelope[T](data: T) -> ApiEnvelope[T]:
    """Build a successful v1 response."""
    return ApiEnvelope[T](data=data)


def error_envelope(
    code: str,
    message: str,
    *,
    details: dict[str, JsonValue] | None = None,
) -> ApiEnvelope[dict[str, JsonValue]]:
    """Build a failed v1 response."""
    return ApiEnvelope[dict[str, JsonValue]](
        error=ApiError(code=code, message=message, details=details or {})
    )
