"""Modal screens and pure form state for the Textual interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from pydantic import JsonValue, ValidationError
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Static, TextArea

from friction.application import ArchiveFilter, ItemQuery
from friction.domain import CreateItem, FrictionItem, ItemPatch, ItemSource, ItemStatus
from friction.interfaces.context import GIT_CONTEXT_FIELDS, git_context


def _tags(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _optional(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _positive_integer(value: str, label: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        result = int(stripped)
    except ValueError as error:
        raise ValueError(f"{label} must be a positive integer.") from error
    if result < 1:
        raise ValueError(f"{label} must be a positive integer.")
    return result


@dataclass(frozen=True)
class QueryState:
    """Complete list/search state owned by the TUI."""

    search_text: str = ""
    statuses: tuple[ItemStatus, ...] = ()
    sources: tuple[ItemSource, ...] = ()
    repo: str | None = None
    tags: tuple[str, ...] = ()
    archive: ArchiveFilter = ArchiveFilter.ACTIVE

    def item_query(self, *, limit: int, offset: int) -> ItemQuery:
        return ItemQuery(
            statuses=self.statuses,
            sources=self.sources,
            repo=self.repo,
            tags=self.tags,
            archive=self.archive,
            limit=limit,
            offset=offset,
        )

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.search_text:
            parts.append(f"/{self.search_text}")
        if self.statuses:
            parts.append("status=" + ",".join(value.value for value in self.statuses))
        if self.sources:
            parts.append("source=" + ",".join(value.value for value in self.sources))
        if self.repo:
            parts.append(f"repo={self.repo}")
        if self.tags:
            parts.append("tags=" + ",".join(self.tags))
        if self.archive is not ArchiveFilter.ACTIVE:
            parts.append(f"archive={self.archive.value}")
        return " ".join(parts) or "active · all statuses"


@dataclass(frozen=True)
class ItemFormValues:
    """Validated values returned by an add or edit form."""

    note: str
    tags: tuple[str, ...]
    path: str | None
    line: int | None
    column: int | None
    cwd: str | None
    filetype: str | None
    git_root: str | None
    git_repo: str | None
    git_branch: str | None
    git_commit: str | None
    metadata: dict[str, JsonValue]

    def create_command(self) -> CreateItem:
        metadata = dict(self.metadata)
        metadata["interface"] = "tui"
        return CreateItem(
            note=self.note,
            source=ItemSource.CLI,
            tags=self.tags,
            path=self.path,
            line=self.line,
            column=self.column,
            cwd=self.cwd,
            filetype=self.filetype,
            git_root=self.git_root,
            git_repo=self.git_repo,
            git_branch=self.git_branch,
            git_commit=self.git_commit,
            metadata=metadata,
        )

    def patch_against(self, item: FrictionItem) -> ItemPatch:
        values: dict[str, Any] = {
            "note": self.note,
            "tags": self.tags,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "cwd": self.cwd,
            "filetype": self.filetype,
            "git_root": self.git_root,
            "git_repo": self.git_repo,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
            "metadata": self.metadata,
        }
        changes = {
            key: value for key, value in values.items() if getattr(item, key) != value
        }
        return ItemPatch.model_validate(changes)


class ConfirmScreen(ModalScreen[bool]):
    """Small reusable confirmation dialog."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "No"),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.question)
            with Horizontal():
                yield Button("Yes", variant="primary", id="confirm-yes")
                yield Button("No", id="confirm-no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class HelpScreen(ModalScreen[None]):
    """Vim interaction and lifecycle help."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    HELP = """Friction TUI

j/k move · gg/G first/last · ctrl+u/ctrl+d half page
l detail · h table · / search · a add · i edit · gf open source
za archive/unarchive · : command line · ? help · escape normal mode

:e :q :add :edit :done :dismiss :reopen :archive :unarchive
:open :filters :help

Status transitions: open → done/dismissed; done/dismissed → open.
Every mutation uses the displayed revision and never retries a conflict."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-dialog"):
            yield Static(self.HELP)
            yield Button("Close", id="help-close")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss(None)


class FilterScreen(ModalScreen[QueryState | None]):
    """Complete query filter editor."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "next_field", "Next", show=False),
        Binding("k", "previous_field", "Previous", show=False),
        Binding("i", "edit_field", "Edit", show=False),
        Binding("enter", "edit_field", "Edit", show=False),
        Binding("colon", "command", "Command", show=False),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Apply"),
    ]

    FIELD_IDS = (
        "filter-search",
        "filter-statuses",
        "filter-sources",
        "filter-repo",
        "filter-tags",
        "filter-archive",
    )

    def __init__(self, state: QueryState) -> None:
        super().__init__()
        self.state = state
        self._field_index = 0
        self._editing = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="filter-dialog"):
            yield Label("Filters")
            yield Input(
                value=self.state.search_text, placeholder="Search", id="filter-search"
            )
            yield Input(
                value=",".join(value.value for value in self.state.statuses),
                placeholder="Statuses: open,done,dismissed",
                id="filter-statuses",
            )
            yield Input(
                value=",".join(value.value for value in self.state.sources),
                placeholder="Sources: cli,emacs,nvim,mcp,web,import",
                id="filter-sources",
            )
            yield Input(
                value=self.state.repo or "",
                placeholder="Exact repository",
                id="filter-repo",
            )
            yield Input(
                value=",".join(self.state.tags),
                placeholder="Tags (all required)",
                id="filter-tags",
            )
            yield Input(
                value=self.state.archive.value,
                placeholder="active, archived, or all",
                id="filter-archive",
            )
            yield Static("", id="filter-error")
            yield Input(placeholder=":w, :q, or :wq", id="filter-command")
            with Horizontal():
                yield Button("Apply", variant="primary", id="filter-apply")
                yield Button("Clear", id="filter-clear")
                yield Button("Cancel", id="filter-cancel")

    def on_mount(self) -> None:
        self.query_one("#filter-apply", Button).focus()
        self._select_field(0)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id in self.FIELD_IDS:
            self._editing = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-command":
            command = event.value.strip().removeprefix(":")
            if command in {"w", "wq"}:
                self._submit()
            elif command == "q":
                self.dismiss(None)
            else:
                self.query_one("#filter-error", Static).update(
                    "Form commands are :w, :wq, and :q."
                )
        else:
            self._leave_editing()

    def action_cancel(self) -> None:
        if self._editing:
            self._leave_editing()
        else:
            self.dismiss(None)

    def action_next_field(self) -> None:
        self._select_field(self._field_index + 1)

    def action_previous_field(self) -> None:
        self._select_field(self._field_index - 1)

    def action_edit_field(self) -> None:
        self._editing = True
        self.query_one("#" + self.FIELD_IDS[self._field_index], Input).focus()

    def action_command(self) -> None:
        command = self.query_one("#filter-command", Input)
        command.display = True
        command.value = ""
        command.focus()

    def _select_field(self, index: int) -> None:
        self._field_index = index % len(self.FIELD_IDS)
        for field_id in self.FIELD_IDS:
            self.query_one("#" + field_id).remove_class("form-selected")
        self.query_one("#" + self.FIELD_IDS[self._field_index]).add_class(
            "form-selected"
        )

    def _leave_editing(self) -> None:
        self._editing = False
        command = self.query_one("#filter-command", Input)
        command.display = False
        self.query_one("#filter-apply", Button).focus()

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "filter-cancel":
            self.dismiss(None)
        elif event.button.id == "filter-clear":
            self.dismiss(QueryState())
        else:
            self._submit()

    def _submit(self) -> None:
        try:
            statuses = tuple(
                ItemStatus(value.casefold())
                for value in _tags(self.query_one("#filter-statuses", Input).value)
            )
            sources = tuple(
                ItemSource(value.casefold())
                for value in _tags(self.query_one("#filter-sources", Input).value)
            )
            archive = ArchiveFilter(
                self.query_one("#filter-archive", Input).value.strip().casefold()
            )
            state = QueryState(
                search_text=self.query_one("#filter-search", Input).value.strip(),
                statuses=statuses,
                sources=sources,
                repo=_optional(self.query_one("#filter-repo", Input).value),
                tags=_tags(self.query_one("#filter-tags", Input).value),
                archive=archive,
            )
        except ValueError:
            self.query_one("#filter-error", Static).update(
                "Use known status/source values and archive=active, archived, or all."
            )
            return
        self.dismiss(state)


class ItemFormScreen(ModalScreen[None]):
    """Vim-friendly add/edit form that remains open during persistence."""

    class Submitted(Message):
        def __init__(self, screen: ItemFormScreen, values: ItemFormValues) -> None:
            super().__init__()
            self.screen = screen
            self.values = values

    class ReloadRequested(Message):
        def __init__(self, screen: ItemFormScreen, identifier: UUID) -> None:
            super().__init__()
            self.screen = screen
            self.identifier = identifier

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "next_field", "Next", show=False),
        Binding("k", "previous_field", "Previous", show=False),
        Binding("i", "edit_field", "Edit", show=False),
        Binding("enter", "edit_field", "Edit", show=False),
        Binding("colon", "command", "Command", show=False),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Save", priority=True),
    ]

    FIELD_IDS = (
        "form-note",
        "form-tags",
        "form-path",
        "form-line",
        "form-column",
        "form-cwd",
        "form-filetype",
        "form-git-root",
        "form-git-repo",
        "form-git-branch",
        "form-git-commit",
        "form-metadata",
    )

    def __init__(
        self, *, item: FrictionItem | None = None, launch_cwd: Path | None = None
    ) -> None:
        super().__init__()
        self.item = item
        self.expected_revision = item.revision if item is not None else None
        self.launch_cwd = (launch_cwd or Path.cwd()).resolve()
        self.dirty = False
        self._ready = False
        self._editing = False
        self._field_index = 0

    def compose(self) -> ComposeResult:
        item = self.item
        cwd = item.cwd if item is not None else str(self.launch_cwd)
        discovered = git_context(cwd) if item is None and cwd is not None else {}
        with VerticalScroll(id="item-form-dialog"):
            yield Label("Edit friction" if item is not None else "Add friction")
            yield Label("Note")
            yield TextArea(item.note if item is not None else "", id="form-note")
            yield Input(
                value=",".join(item.tags) if item is not None else "",
                placeholder="Tags",
                id="form-tags",
            )
            with Collapsible(title="Advanced", collapsed=True):
                yield Input(
                    value=item.path or "" if item is not None else "",
                    placeholder="Path",
                    id="form-path",
                )
                yield Input(
                    value=str(item.line or "") if item is not None else "",
                    placeholder="Line",
                    id="form-line",
                )
                yield Input(
                    value=str(item.column or "") if item is not None else "",
                    placeholder="Column",
                    id="form-column",
                )
                yield Input(
                    value=cwd or "", placeholder="Working directory", id="form-cwd"
                )
                yield Input(
                    value=item.filetype or "" if item is not None else "",
                    placeholder="Filetype",
                    id="form-filetype",
                )
                yield Input(
                    value=item.git_root or ""
                    if item is not None
                    else discovered.get("git_root") or "",
                    placeholder="Git root",
                    id="form-git-root",
                )
                yield Input(
                    value=item.git_repo or ""
                    if item is not None
                    else discovered.get("git_repo") or "",
                    placeholder="Git repository",
                    id="form-git-repo",
                )
                yield Input(
                    value=item.git_branch or ""
                    if item is not None
                    else discovered.get("git_branch") or "",
                    placeholder="Git branch",
                    id="form-git-branch",
                )
                yield Input(
                    value=item.git_commit or ""
                    if item is not None
                    else discovered.get("git_commit") or "",
                    placeholder="Git commit",
                    id="form-git-commit",
                )
                yield TextArea(
                    json.dumps(
                        item.metadata if item is not None else {},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    id="form-metadata",
                )
                if item is None:
                    yield Button("Refresh Git context", id="form-refresh-git")
            yield Static("", id="form-error")
            with Horizontal(id="form-conflict-actions"):
                yield Button("Reload latest", id="form-reload")
                yield Button("Cancel", id="form-conflict-cancel")
            yield Input(placeholder=":w, :q, or :wq", id="form-command")
            with Horizontal():
                yield Button("Save", variant="primary", id="form-save")
                yield Button("Cancel", id="form-cancel")

    def on_mount(self) -> None:
        self._ready = True
        self.query_one("#form-save", Button).focus()
        self._select_field(0)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id in self.FIELD_IDS:
            self._editing = True

    def on_input_changed(self, _event: Input.Changed) -> None:
        if self._ready and _event.input.id != "form-command":
            self.dirty = True

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        if self._ready:
            self.dirty = True

    def action_submit(self) -> None:
        self.submit()

    def action_cancel(self) -> None:
        if self._editing:
            self._leave_editing()
        else:
            self.request_cancel()

    def action_next_field(self) -> None:
        self._select_field(self._field_index + 1)

    def action_previous_field(self) -> None:
        self._select_field(self._field_index - 1)

    def action_edit_field(self) -> None:
        self._editing = True
        self.query_one("#" + self.FIELD_IDS[self._field_index]).focus()

    def action_command(self) -> None:
        command = self.query_one("#form-command", Input)
        command.display = True
        command.value = ""
        command.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "form-command":
            command = event.value.strip().removeprefix(":")
            if command in {"w", "wq"}:
                self.submit()
            elif command == "q":
                self.request_cancel()
            else:
                self.show_error("Form commands are :w, :wq, and :q.")
        else:
            self._leave_editing()

    def _select_field(self, index: int) -> None:
        self._field_index = index % len(self.FIELD_IDS)
        for field_id in self.FIELD_IDS:
            self.query_one("#" + field_id).remove_class("form-selected")
        self.query_one("#" + self.FIELD_IDS[self._field_index]).add_class(
            "form-selected"
        )

    def _leave_editing(self) -> None:
        self._editing = False
        command = self.query_one("#form-command", Input)
        command.display = False
        self.query_one("#form-save", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "form-save":
            self.submit()
        elif event.button.id == "form-cancel":
            self.request_cancel()
        elif event.button.id == "form-refresh-git":
            self.refresh_git_context()
        elif event.button.id == "form-reload" and self.item is not None:
            self.post_message(self.ReloadRequested(self, self.item.id))
        elif event.button.id == "form-conflict-cancel":
            self.dismiss(None)

    def submit(self) -> None:
        try:
            note = self.query_one("#form-note", TextArea).text.strip()
            if not note:
                raise ValueError("Note must not be empty.")
            metadata_value = json.loads(
                self.query_one("#form-metadata", TextArea).text or "{}"
            )
            if not isinstance(metadata_value, dict):
                raise ValueError("Metadata must be one JSON object.")
            values = ItemFormValues(
                note=note,
                tags=_tags(self.query_one("#form-tags", Input).value),
                path=_optional(self.query_one("#form-path", Input).value),
                line=_positive_integer(
                    self.query_one("#form-line", Input).value, "Line"
                ),
                column=_positive_integer(
                    self.query_one("#form-column", Input).value, "Column"
                ),
                cwd=_optional(self.query_one("#form-cwd", Input).value),
                filetype=_optional(self.query_one("#form-filetype", Input).value),
                git_root=_optional(self.query_one("#form-git-root", Input).value),
                git_repo=_optional(self.query_one("#form-git-repo", Input).value),
                git_branch=_optional(self.query_one("#form-git-branch", Input).value),
                git_commit=_optional(self.query_one("#form-git-commit", Input).value),
                metadata=metadata_value,
            )
            if self.item is None:
                values.create_command()
            else:
                values.patch_against(self.item)
        except (ValueError, json.JSONDecodeError, ValidationError) as error:
            self.show_error(str(error))
            return
        self.post_message(self.Submitted(self, values))

    def show_error(self, message: str) -> None:
        self.query_one("#form-error", Static).update(message)

    def show_conflict(self, message: str) -> None:
        self.show_error(message)
        self.query_one("#form-conflict-actions", Horizontal).display = True

    def reload_item(self, item: FrictionItem) -> None:
        """Replace a conflicted draft with current persisted values."""
        self.item = item
        self.expected_revision = item.revision
        self._ready = False
        note = self.query_one("#form-note", TextArea)
        with note.prevent(TextArea.Changed):
            note.text = item.note
        values = {
            "form-tags": ",".join(item.tags),
            "form-path": item.path or "",
            "form-line": str(item.line or ""),
            "form-column": str(item.column or ""),
            "form-cwd": item.cwd or "",
            "form-filetype": item.filetype or "",
            "form-git-root": item.git_root or "",
            "form-git-repo": item.git_repo or "",
            "form-git-branch": item.git_branch or "",
            "form-git-commit": item.git_commit or "",
        }
        for field_id, value in values.items():
            widget = self.query_one("#" + field_id, Input)
            with widget.prevent(Input.Changed):
                widget.value = value
        metadata = self.query_one("#form-metadata", TextArea)
        with metadata.prevent(TextArea.Changed):
            metadata.text = json.dumps(item.metadata, ensure_ascii=False, indent=2)
        self.query_one("#form-conflict-actions", Horizontal).display = False
        self.query_one("#form-save").disabled = False
        self.show_error("")
        self.dirty = False
        self._ready = True

    def request_cancel(self) -> None:
        if not self.dirty:
            self.dismiss(None)
            return

        def finish(confirmed: bool | None) -> None:
            if confirmed:
                self.dismiss(None)

        self.app.push_screen(ConfirmScreen("Discard unsaved changes?"), finish)

    def refresh_git_context(self) -> None:
        cwd = _optional(self.query_one("#form-cwd", Input).value)
        if cwd is None:
            self.show_error("Working directory is required for Git discovery.")
            return
        context = git_context(cwd)
        for field in GIT_CONTEXT_FIELDS:
            widget = self.query_one("#form-" + field.replace("_", "-"), Input)
            if not widget.value:
                widget.value = context[field] or ""
