"""Widgets used by the Textual interface."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from rich.text import Text
from textual.binding import BindingType
from textual.widgets import DataTable, Static

from friction.domain import FrictionEvent, FrictionItem


def _local_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


class ItemTable(DataTable[str]):
    """A deterministic UUID-keyed table of friction items."""

    BINDINGS: ClassVar[list[BindingType]] = []

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns("Status", "Note", "Source", "Repo", "Tags", "Created", "ID")

    def replace_items(
        self, items: Iterable[FrictionItem], *, selected_id: UUID | None = None
    ) -> None:
        rows = list(items)
        self.clear(columns=False)
        selected_row = 0
        for row_index, item in enumerate(rows):
            status = item.status.value.upper()
            if item.archived_at is not None:
                status = f"{status} ARCH"
            note = item.note.splitlines()[0] if item.note.splitlines() else item.note
            self.add_row(
                status,
                note,
                item.source.value,
                item.git_repo or "-",
                ",".join(item.tags) or "-",
                _local_time(item.created_at),
                str(item.id)[:8],
                key=str(item.id),
            )
            if item.id == selected_id:
                selected_row = row_index
        if rows:
            self.move_cursor(row=selected_row, column=0, animate=False)

    def append_items(self, items: Iterable[FrictionItem]) -> None:
        for item in items:
            status = item.status.value.upper()
            if item.archived_at is not None:
                status = f"{status} ARCH"
            note = item.note.splitlines()[0] if item.note.splitlines() else item.note
            self.add_row(
                status,
                note,
                item.source.value,
                item.git_repo or "-",
                ",".join(item.tags) or "-",
                _local_time(item.created_at),
                str(item.id)[:8],
                key=str(item.id),
            )

    @property
    def selected_id(self) -> UUID | None:
        if self.row_count == 0 or not self.is_valid_row_index(self.cursor_row):
            return None
        row_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        if row_key.value is None:
            return None
        return UUID(row_key.value)


class DetailPane(Static):
    """Complete item state and chronological event history."""

    def show_empty(self) -> None:
        self.update("No matching friction items")

    def show_item(
        self,
        item: FrictionItem,
        events: Iterable[FrictionEvent] | None = None,
        *,
        show_event_payloads: bool = True,
    ) -> None:
        lines = [item.note, ""]
        values = (
            ("status", item.status.value),
            ("revision", str(item.revision)),
            ("source", item.source.value),
            ("created", _local_time(item.created_at)),
            ("updated", _local_time(item.updated_at)),
            ("archived", _local_time(item.archived_at)),
            ("tags", ", ".join(item.tags) or "-"),
            ("path", item.path or "-"),
            ("line", str(item.line) if item.line is not None else "-"),
            ("column", str(item.column) if item.column is not None else "-"),
            ("cwd", item.cwd or "-"),
            ("filetype", item.filetype or "-"),
            ("git root", item.git_root or "-"),
            ("git repo", item.git_repo or "-"),
            ("git branch", item.git_branch or "-"),
            ("git commit", item.git_commit or "-"),
        )
        lines.extend(f"{label}: {value}" for label, value in values)
        lines.extend(
            ("", "metadata:", json.dumps(item.metadata, ensure_ascii=False, indent=2))
        )
        event_values = list(events or ())
        if events is None:
            lines.extend(("", "history: loading…"))
        elif not event_values:
            lines.extend(("", "history: -"))
        else:
            lines.extend(("", "history:"))
            for event in event_values:
                revision = (
                    f"r{event.from_revision} → r{event.to_revision}"
                    if event.from_revision is not None
                    else f"→ r{event.to_revision}"
                )
                occurred = _local_time(event.occurred_at)
                lines.append(f"{occurred} {event.event_type.value} {revision}")
                if event.payload and show_event_payloads:
                    lines.append(
                        "  "
                        + json.dumps(
                            event.payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
        self.update(Text("\n".join(lines)))
