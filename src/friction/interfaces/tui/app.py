"""Textual application for complete single-item Friction management."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Static

from friction.application import FrictionService
from friction.domain import (
    FrictionError,
    FrictionEvent,
    FrictionItem,
    InvalidTransitionError,
    ItemStatus,
)
from friction.interfaces.editor import EditorError, launch_editor, resolved_source
from friction.interfaces.tui.screens import (
    ConfirmScreen,
    FilterScreen,
    HelpScreen,
    ItemFormScreen,
    ItemFormValues,
    QueryState,
)
from friction.interfaces.tui.widgets import DetailPane, ItemTable

PAGE_SIZE = 100


class FrictionTui(App[None]):
    """Local Vim-style terminal interface over one injected service."""

    TITLE = "Friction"
    CSS = """
    Screen {
        layout: vertical;
    }
    #title-bar {
        height: 1;
        padding: 0 1;
        background: $primary;
        color: $text;
        text-style: bold;
    }
    #main-pane {
        height: 1fr;
        layout: horizontal;
    }
    #item-table {
        width: 58%;
        height: 1fr;
    }
    #detail-scroll {
        width: 42%;
        height: 1fr;
        border-left: solid $primary;
        padding: 0 1;
    }
    #detail-pane {
        width: 100%;
        height: auto;
    }
    #search-line, #command-line, #form-command, #filter-command {
        display: none;
        height: 3;
        border: tall $primary;
    }
    #status-line {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    #fatal-banner {
        display: none;
        height: auto;
        padding: 1;
        background: $error;
        color: $text;
    }
    ModalScreen {
        align: center middle;
        background: $background 65%;
    }
    #confirm-dialog, #help-dialog, #filter-dialog, #item-form-dialog {
        width: 92%;
        max-width: 92;
        max-height: 92%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #confirm-dialog {
        width: 90%;
        max-width: 60;
        height: auto;
    }
    #form-note, #form-metadata {
        height: 8;
    }
    #form-error, #filter-error {
        min-height: 1;
        color: $error;
    }
    .form-selected {
        border: tall $accent;
    }
    #form-conflict-actions {
        display: none;
        height: auto;
    }
    Screen.narrow #main-pane {
        layout: vertical;
    }
    Screen.narrow #item-table, Screen.narrow #detail-scroll {
        width: 100%;
        height: 1fr;
    }
    Screen.narrow #detail-scroll {
        border-left: none;
        border-top: solid $primary;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "next_item", "Next", show=False),
        Binding("k", "previous_item", "Previous", show=False),
        Binding("g", "prefix_g", "g", show=False),
        Binding("shift+g", "last_item", "Last", show=False),
        Binding("z", "prefix_z", "z", show=False),
        Binding("ctrl+u", "half_page_up", "Half page up", show=False),
        Binding("ctrl+d", "half_page_down", "Half page down", show=False),
        Binding("l", "focus_detail", "Detail", show=False),
        Binding("h", "focus_table", "Table", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("a", "add", "Add", show=False),
        Binding("i", "edit", "Edit", show=False),
        Binding("colon", "command", "Command", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("escape", "escape", "Normal mode", show=False),
    ]

    def __init__(
        self,
        service: FrictionService,
        *,
        database_path: str | Path | None = None,
        launch_cwd: Path | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.database_path = Path(database_path).expanduser() if database_path else None
        self.launch_cwd = (launch_cwd or Path.cwd()).resolve()
        self.query_state = QueryState()
        self.items: list[FrictionItem] = []
        self._items_by_id: dict[UUID, FrictionItem] = {}
        self.pages_loaded = 1
        self.has_more = False
        self.generation = 0
        self.pending_prefix: str | None = None
        self._prefix_timer: Timer | None = None
        self._mutation_busy = False
        self._detail_generation = 0
        self._command_history: list[str] = []
        self._command_history_index = 0

    def compose(self) -> ComposeResult:
        yield Static("Friction", id="title-bar")
        with Horizontal(id="main-pane"):
            yield ItemTable(id="item-table")
            with VerticalScroll(id="detail-scroll"):
                yield DetailPane("No matching friction items", id="detail-pane")
        yield Input(placeholder="/ search; Enter applies", id="search-line")
        yield Input(placeholder=": command", id="command-line")
        yield Static(
            "j/k move · / search · a add · i edit · : commands · ? help",
            id="status-line",
        )
        yield Static("", id="fatal-banner")

    def on_mount(self) -> None:
        self.query_one(ItemTable).focus()
        self.refresh_items()

    def on_resize(self, event: events.Resize) -> None:
        self.screen.set_class(event.size.width < 100, "narrow")

    def on_key(self, event: events.Key) -> None:
        command = self.query_one("#command-line", Input)
        if command.display and command.has_focus and event.key in {"j", "k"}:
            self._move_command_history(-1 if event.key == "k" else 1)
            event.prevent_default()
            event.stop()
            return
        if self.pending_prefix is None:
            return
        pending = self.pending_prefix
        key = event.key
        self._clear_prefix()
        event.prevent_default()
        event.stop()
        if pending == "g" and key == "g":
            self.action_first_item()
        elif pending == "g" and key == "f":
            self.action_open_source()
        elif pending == "z" and key == "a":
            self.action_toggle_archive()
        else:
            self.set_status(f"Unknown sequence: {pending}{key}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-line":
            self.query_state = QueryState(
                search_text=event.value.strip(),
                statuses=self.query_state.statuses,
                sources=self.query_state.sources,
                repo=self.query_state.repo,
                tags=self.query_state.tags,
                archive=self.query_state.archive,
            )
            self._hide_input(event.input)
            self.pages_loaded = 1
            self.refresh_items(preserve_selection=False)
        elif event.input.id == "command-line":
            self._execute_command(event.value)

    def on_data_table_row_highlighted(self, event: ItemTable.RowHighlighted) -> None:
        if event.row_key.value is None:
            return
        identifier = UUID(event.row_key.value)
        item = self._items_by_id.get(identifier)
        if item is None:
            return
        self.query_one(DetailPane).show_item(item)
        self._detail_generation += 1
        self._load_history(self._detail_generation, identifier)
        if event.cursor_row == len(self.items) - 1 and self.has_more:
            self._load_next_page()

    def set_status(self, message: str) -> None:
        self.query_one("#status-line", Static).update(message)

    def refresh_items(self, *, preserve_selection: bool = True) -> None:
        if isinstance(self.screen, ModalScreen):
            self.set_status("Close the open dialog before refreshing.")
            return
        selected = self.query_one(ItemTable).selected_id if preserve_selection else None
        self.generation += 1
        self.set_status("Loading…")
        self._load_query(self.generation, self.pages_loaded, selected)

    @work(thread=True, exclusive=True, group="query", exit_on_error=False)
    def _load_query(
        self, generation: int, page_count: int, selected_id: UUID | None
    ) -> None:
        try:
            loaded: list[FrictionItem] = []
            seen: set[UUID] = set()
            last_page_count = 0
            for page_index in range(max(page_count, 1)):
                query = self.query_state.item_query(
                    limit=PAGE_SIZE, offset=page_index * PAGE_SIZE
                )
                page = (
                    self.service.search(self.query_state.search_text, query)
                    if self.query_state.search_text
                    else self.service.list(query)
                )
                last_page_count = len(page)
                for item in page:
                    if item.id not in seen:
                        seen.add(item.id)
                        loaded.append(item)
                if len(page) < PAGE_SIZE:
                    break
        except Exception as error:
            self.call_from_thread(self._query_failed, generation, error)
            return
        self.call_from_thread(
            self._query_loaded,
            generation,
            loaded,
            selected_id,
            last_page_count == PAGE_SIZE,
        )

    def _query_loaded(
        self,
        generation: int,
        items: list[FrictionItem],
        selected_id: UUID | None,
        has_more: bool,
    ) -> None:
        if generation != self.generation:
            return
        previous_selection = selected_id
        self.items = items
        self._items_by_id = {item.id: item for item in items}
        self.has_more = has_more
        table = self.query_one(ItemTable)
        table.replace_items(items, selected_id=selected_id)
        self.query_one("#fatal-banner", Static).display = False
        self._update_title()
        if not items:
            self.query_one(DetailPane).show_empty()
        elif (
            previous_selection is not None
            and previous_selection not in self._items_by_id
        ):
            self.set_status(
                f"{len(items)} item(s) · previous selection no longer matches filters"
            )
            return
        self.set_status(f"{len(items)} item(s) · loaded {self.pages_loaded} page(s)")

    def _query_failed(self, generation: int, error: Exception) -> None:
        if generation != self.generation:
            return
        message = f"storage_error: {error}"
        if not self.items:
            banner = self.query_one("#fatal-banner", Static)
            banner.update(message + " · use :e to retry or :q to quit")
            banner.display = True
        self.set_status(message)

    def _load_next_page(self) -> None:
        if not self.has_more:
            return
        self.pages_loaded += 1
        self.refresh_items()

    @work(thread=True, exclusive=True, group="detail", exit_on_error=False)
    def _load_history(self, generation: int, identifier: UUID) -> None:
        try:
            events = self.service.events(identifier)
        except Exception as error:
            self.call_from_thread(
                self.set_status, f"storage_error: unable to load history: {error}"
            )
            return
        self.call_from_thread(self._history_loaded, generation, identifier, events)

    def _history_loaded(
        self, generation: int, identifier: UUID, events: list[FrictionEvent]
    ) -> None:
        if generation != self._detail_generation:
            return
        item = self._items_by_id.get(identifier)
        if item is not None and self.query_one(ItemTable).selected_id == identifier:
            self.query_one(DetailPane).show_item(
                item, events, show_event_payloads=self.size.height >= 24
            )

    def _selected_item(self) -> FrictionItem | None:
        identifier = self.query_one(ItemTable).selected_id
        return self._items_by_id.get(identifier) if identifier is not None else None

    def action_next_item(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            table.move_cursor(row=min(table.cursor_row + 1, table.row_count - 1))

    def action_previous_item(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            table.move_cursor(row=max(table.cursor_row - 1, 0))

    def action_first_item(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            table.move_cursor(row=0)

    def action_last_item(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            table.move_cursor(row=table.row_count - 1)

    def action_half_page_up(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            distance = max(table.size.height // 2, 1)
            table.move_cursor(row=max(table.cursor_row - distance, 0))

    def action_half_page_down(self) -> None:
        table = self.query_one(ItemTable)
        if table.row_count:
            distance = max(table.size.height // 2, 1)
            table.move_cursor(row=min(table.cursor_row + distance, table.row_count - 1))

    def action_focus_detail(self) -> None:
        self.query_one("#detail-scroll", VerticalScroll).focus()

    def action_focus_table(self) -> None:
        self.query_one(ItemTable).focus()

    def action_prefix_g(self) -> None:
        self._set_prefix("g")

    def action_prefix_z(self) -> None:
        self._set_prefix("z")

    def _set_prefix(self, prefix: str) -> None:
        self.pending_prefix = prefix
        if self._prefix_timer is not None:
            self._prefix_timer.stop()
        self._prefix_timer = self.set_timer(1.0, self._clear_prefix)
        self.set_status(f"pending: {prefix}")

    def _clear_prefix(self) -> None:
        self.pending_prefix = None
        if self._prefix_timer is not None:
            self._prefix_timer.stop()
            self._prefix_timer = None

    def action_search(self) -> None:
        search = self.query_one("#search-line", Input)
        search.value = self.query_state.search_text
        search.display = True
        search.focus()
        search.cursor_position = len(search.value)

    def action_command(self) -> None:
        command = self.query_one("#command-line", Input)
        command.value = ""
        command.display = True
        command.focus()
        self._command_history_index = len(self._command_history)

    def action_escape(self) -> None:
        self._clear_prefix()
        for selector in ("#search-line", "#command-line"):
            widget = self.query_one(selector, Input)
            if widget.display:
                self._hide_input(widget)
        self.query_one(ItemTable).focus()

    def _hide_input(self, widget: Input) -> None:
        widget.display = False
        self.query_one(ItemTable).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_add(self) -> None:
        self.push_screen(ItemFormScreen(launch_cwd=self.launch_cwd))

    def action_edit(self) -> None:
        item = self._selected_item()
        if item is None:
            self.set_status("Select an item to edit.")
            return
        self.push_screen(ItemFormScreen(item=item, launch_cwd=self.launch_cwd))

    def on_item_form_screen_submitted(self, message: ItemFormScreen.Submitted) -> None:
        if self._mutation_busy:
            message.screen.show_error("A mutation is already running.")
            return
        self._mutation_busy = True
        message.screen.query_one("#form-save").disabled = True
        self._save_form(message.screen, message.values)

    def on_item_form_screen_reload_requested(
        self, message: ItemFormScreen.ReloadRequested
    ) -> None:
        self._reload_form(message.screen, message.identifier)

    @work(thread=True, exclusive=True, group="form-reload", exit_on_error=False)
    def _reload_form(self, screen: ItemFormScreen, identifier: UUID) -> None:
        try:
            item = self.service.get(identifier)
        except Exception as error:
            self.call_from_thread(screen.show_error, f"storage_error: {error}")
            return
        self.call_from_thread(screen.reload_item, item)

    @work(thread=True, exclusive=True, group="mutation", exit_on_error=False)
    def _save_form(self, screen: ItemFormScreen, values: ItemFormValues) -> None:
        try:
            if screen.item is None:
                item = self.service.create(values.create_command())
            else:
                item = self.service.update(
                    screen.item.id,
                    values.patch_against(screen.item),
                    expected_revision=screen.expected_revision or screen.item.revision,
                )
        except FrictionError as error:
            self.call_from_thread(self._form_failed, screen, error)
            return
        except Exception as error:
            self.call_from_thread(self._form_failed, screen, error)
            return
        self.call_from_thread(self._form_saved, screen, item)

    def _form_saved(self, screen: ItemFormScreen, item: FrictionItem) -> None:
        self._mutation_busy = False
        if screen.is_attached:
            screen.dismiss(None)
        self.set_status(f"Saved {str(item.id)[:8]} at revision {item.revision}.")
        self.refresh_items()

    def _form_failed(self, screen: ItemFormScreen, error: Exception) -> None:
        self._mutation_busy = False
        if not screen.is_attached:
            return
        screen.query_one("#form-save").disabled = False
        if isinstance(error, FrictionError):
            message = f"{error.code}: {error.message}"
            if error.code == "revision_conflict":
                screen.show_conflict(message)
                return
            screen.show_error(message)
        else:
            screen.show_error(f"storage_error: {error}")

    def _mutate_selected(self, action: str) -> None:
        if self._mutation_busy:
            self.set_status("A mutation is already running.")
            return
        item = self._selected_item()
        if item is None:
            self.set_status("Select an item first.")
            return
        try:
            if action in {"done", "dismiss"} and item.status is not ItemStatus.OPEN:
                raise InvalidTransitionError(item.status.value, action)
            if action == "reopen" and item.status is ItemStatus.OPEN:
                raise InvalidTransitionError(item.status.value, ItemStatus.OPEN.value)
            if action == "archive" and item.archived_at is not None:
                self.set_status("The selected item is already archived.")
                return
            if action == "unarchive" and item.archived_at is None:
                self.set_status("The selected item is not archived.")
                return
        except InvalidTransitionError as error:
            self.set_status(error.message)
            return
        self._mutation_busy = True
        self._mutation(action, item.id, item.revision)

    @work(thread=True, exclusive=True, group="mutation", exit_on_error=False)
    def _mutation(self, action: str, identifier: UUID, revision: int) -> None:
        try:
            operation = {
                "done": self.service.mark_done,
                "dismiss": self.service.dismiss,
                "reopen": self.service.reopen,
                "archive": self.service.archive,
                "unarchive": self.service.unarchive,
            }[action]
            item = operation(identifier, expected_revision=revision)
        except FrictionError as error:
            self.call_from_thread(self._mutation_failed, error)
            return
        except Exception as error:
            self.call_from_thread(self._mutation_failed, error)
            return
        self.call_from_thread(self._mutation_succeeded, action, item)

    def _mutation_succeeded(self, action: str, item: FrictionItem) -> None:
        self._mutation_busy = False
        self.set_status(f"{action}: {str(item.id)[:8]} → revision {item.revision}")
        self.refresh_items()

    def _mutation_failed(self, error: Exception) -> None:
        self._mutation_busy = False
        if isinstance(error, FrictionError):
            self.set_status(f"{error.code}: {error.message}")
            if error.code == "revision_conflict":
                self.refresh_items()
        else:
            self.set_status(f"storage_error: {error}")

    def action_toggle_archive(self) -> None:
        item = self._selected_item()
        if item is None:
            self.set_status("Select an item first.")
            return
        if item.archived_at is not None:
            self._mutate_selected("unarchive")
            return

        def finish(confirmed: bool | None) -> None:
            if confirmed:
                self._mutate_selected("archive")

        self.push_screen(ConfirmScreen("Archive the selected item?"), finish)

    def action_open_source(self) -> None:
        item = self._selected_item()
        if item is None:
            self.set_status("Select an item first.")
            return
        try:
            target = resolved_source(item)
            with self.suspend():
                launch_editor(target, line=item.line, column=item.column)
        except (EditorError, OSError) as error:
            self.set_status(f"validation_error: {error}")
            return
        self.refresh_items()

    def action_filters(self) -> None:
        self.push_screen(FilterScreen(self.query_state), self._filters_applied)

    def _filters_applied(self, state: QueryState | None) -> None:
        if state is None:
            return
        self.query_state = state
        self.pages_loaded = 1
        self.refresh_items(preserve_selection=False)

    def _execute_command(self, raw_command: str) -> None:
        command_input = self.query_one("#command-line", Input)
        command = raw_command.strip().removeprefix(":")
        if not command:
            self._hide_input(command_input)
            return
        if len(self._command_history) == 50:
            self._command_history.pop(0)
        self._command_history.append(command)
        self._command_history_index = len(self._command_history)
        actions: dict[str, Any] = {
            "e": self.refresh_items,
            "q": self.exit,
            "add": self.action_add,
            "edit": self.action_edit,
            "done": lambda: self._mutate_selected("done"),
            "dismiss": lambda: self._mutate_selected("dismiss"),
            "reopen": lambda: self._mutate_selected("reopen"),
            "archive": self.action_toggle_archive,
            "unarchive": lambda: self._mutate_selected("unarchive"),
            "open": self.action_open_source,
            "filters": self.action_filters,
            "help": self.action_help,
        }
        action = actions.get(command)
        if action is None:
            self.set_status(f"Unknown command: :{command}")
            return
        self._hide_input(command_input)
        action()

    def _move_command_history(self, delta: int) -> None:
        if not self._command_history:
            return
        self._command_history_index = min(
            max(self._command_history_index + delta, 0),
            len(self._command_history),
        )
        value = (
            ""
            if self._command_history_index == len(self._command_history)
            else self._command_history[self._command_history_index]
        )
        command = self.query_one("#command-line", Input)
        command.value = value
        command.cursor_position = len(value)

    def _update_title(self) -> None:
        database = self.database_path.name if self.database_path else "default database"
        self.query_one("#title-bar", Static).update(
            f"Friction · {self.query_state.summary} · {database}"
        )
