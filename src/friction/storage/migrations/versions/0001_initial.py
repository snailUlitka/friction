"""Create the Friction v1 schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalized storage, audit history, provenance, and FTS."""
    op.create_table(
        "friction_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.String(length=35), nullable=False),
        sa.Column("updated_at", sa.String(length=35), nullable=False),
        sa.Column("archived_at", sa.String(length=35), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("column", sa.Integer(), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("filetype", sa.String(length=100), nullable=True),
        sa.Column("git_root", sa.Text(), nullable=True),
        sa.Column("git_repo", sa.Text(), nullable=True),
        sa.Column("git_branch", sa.Text(), nullable=True),
        sa.Column("git_commit", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("column IS NULL OR column > 0", name="ck_item_column"),
        sa.CheckConstraint("line IS NULL OR line > 0", name="ck_item_line"),
        sa.CheckConstraint("revision > 0", name="ck_item_revision"),
        sa.CheckConstraint(
            "source IN ('cli', 'emacs', 'nvim', 'mcp', 'web', 'import')",
            name="ck_item_source",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'done', 'dismissed')", name="ck_item_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_friction_items_archived_at", "friction_items", ["archived_at"])
    op.create_index("ix_friction_items_created_at", "friction_items", ["created_at"])
    op.create_index("ix_friction_items_git_repo", "friction_items", ["git_repo"])
    op.create_index("ix_friction_items_source", "friction_items", ["source"])
    op.create_index("ix_friction_items_status", "friction_items", ["status"])

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("occurred_at", sa.String(length=35), nullable=False),
        sa.Column("from_revision", sa.Integer(), nullable=True),
        sa.Column("to_revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.CheckConstraint("to_revision > 0", name="ck_event_to_revision"),
        sa.ForeignKeyConstraint(
            ["item_id"], ["friction_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_item_occurred", "events", ["item_id", "occurred_at"])
    op.create_table(
        "imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_line", sa.Integer(), nullable=False),
        sa.Column("source_format", sa.String(length=30), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.String(length=35), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["friction_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
    )
    op.create_index("ix_imports_item_id", "imports", ["item_id"])
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["friction_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "tag_id"),
    )
    op.execute(
        "CREATE VIRTUAL TABLE friction_items_fts USING fts5("
        "item_id UNINDEXED, note, tags, path, cwd, git_repo)"
    )


def downgrade() -> None:
    """Remove the complete v1 schema for development environments."""
    op.execute("DROP TABLE IF EXISTS friction_items_fts")
    op.drop_table("item_tags")
    op.drop_index("ix_imports_item_id", table_name="imports")
    op.drop_table("imports")
    op.drop_index("ix_events_item_occurred", table_name="events")
    op.drop_table("events")
    op.drop_table("tags")
    op.drop_index("ix_friction_items_status", table_name="friction_items")
    op.drop_index("ix_friction_items_source", table_name="friction_items")
    op.drop_index("ix_friction_items_git_repo", table_name="friction_items")
    op.drop_index("ix_friction_items_created_at", table_name="friction_items")
    op.drop_index("ix_friction_items_archived_at", table_name="friction_items")
    op.drop_table("friction_items")

