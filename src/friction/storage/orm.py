"""SQLAlchemy ORM mappings kept behind the repository adapter."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative metadata used by Alembic."""


item_tags = Table(
    "item_tags",
    Base.metadata,
    Column(
        "item_id",
        String(36),
        ForeignKey("friction_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class FrictionItemRow(Base):
    """Persisted friction item state."""

    __tablename__ = "friction_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'done', 'dismissed')", name="ck_item_status"
        ),
        CheckConstraint(
            "source IN ('cli', 'emacs', 'nvim', 'mcp', 'web', 'import')",
            name="ck_item_source",
        ),
        CheckConstraint("revision > 0", name="ck_item_revision"),
        CheckConstraint("line IS NULL OR line > 0", name="ck_item_line"),
        CheckConstraint("column IS NULL OR column > 0", name="ck_item_column"),
        Index("ix_friction_items_created_at", "created_at"),
        Index("ix_friction_items_status", "status"),
        Index("ix_friction_items_source", "source"),
        Index("ix_friction_items_git_repo", "git_repo"),
        Index("ix_friction_items_archived_at", "archived_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    note: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(35))
    updated_at: Mapped[str] = mapped_column(String(35))
    archived_at: Mapped[str | None] = mapped_column(String(35), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    filetype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    git_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_repo: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    revision: Mapped[int] = mapped_column(Integer)

    tags: Mapped[list[TagRow]] = relationship(
        secondary=item_tags,
        lazy="selectin",
        order_by="TagRow.normalized_name",
    )


class TagRow(Base):
    """Case-insensitively unique tag."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)


class EventRow(Base):
    """Immutable item audit event."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_item_occurred", "item_id", "occurred_at"),
        CheckConstraint("to_revision > 0", name="ck_event_to_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("friction_items.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[str] = mapped_column(String(35))
    from_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_revision: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ImportRow(Base):
    """Provenance for one imported JSONL record."""

    __tablename__ = "imports"
    __table_args__ = (
        UniqueConstraint("fingerprint"),
        Index("ix_imports_item_id", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("friction_items.id", ondelete="CASCADE")
    )
    source_path: Mapped[str] = mapped_column(Text)
    source_line: Mapped[int] = mapped_column(Integer)
    source_format: Mapped[str] = mapped_column(String(30))
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[str] = mapped_column(String(35))


def tag_names(tags: Sequence[TagRow]) -> tuple[str, ...]:
    """Return the canonical tag tuple for a loaded row."""
    return tuple(tag.name for tag in tags)

