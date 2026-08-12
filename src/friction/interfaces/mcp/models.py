"""Structured MCP response models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from friction.contracts import EventData, ItemData


class McpModel(BaseModel):
    """Strict base for MCP-specific output shapes."""

    model_config = ConfigDict(extra="forbid")


class McpItemPage(McpModel):
    """One deterministic page of items."""

    items: list[ItemData]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool


class McpItemDetail(McpModel):
    """One item with optionally requested history."""

    item: ItemData
    events: list[EventData]


class McpEventHistory(McpModel):
    """Complete chronological history for one item."""

    item_id: UUID
    events: list[EventData]
