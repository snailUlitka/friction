import asyncio
from contextlib import nullcontext
from pathlib import Path

import pytest
from textual import events
from textual.containers import Horizontal
from textual.geometry import Size
from textual.widgets import Button, Input, Static, TextArea

from friction.application import ArchiveFilter, ItemQuery
from friction.domain import CreateItem, FrictionItem, ItemPatch, ItemStatus
from friction.interfaces.editor import EditorError
from friction.interfaces.tui import app as tui_app_module
from friction.interfaces.tui.app import FrictionTui
from friction.interfaces.tui.screens import (
    ConfirmScreen,
    FilterScreen,
    HelpScreen,
    ItemFormScreen,
    QueryState,
)
from friction.interfaces.tui.widgets import DetailPane, ItemTable
from friction.storage import create_service


def test_tui_empty_and_narrow_main_screen(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "empty.db"
        app = FrictionTui(create_service(database), database_path=database)
        async with app.run_test(size=(80, 16)) as pilot:
            await pilot.pause(0.1)
            assert app.query_one(ItemTable).row_count == 0
            assert "No matching" in str(app.query_one(DetailPane).render())
            assert database.name in str(app.query_one("#title-bar", Static).render())

    asyncio.run(scenario())


def test_tui_navigation_prefixes_command_history_help_and_widget_details(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = create_service(tmp_path / "navigation.db")
        created = [
            service.create(
                CreateItem(
                    note=f"item {index}\nsecond line",
                    tags=("local",),
                    git_repo="friction",
                    metadata={"index": index},
                )
            )
            for index in range(3)
        ]
        service.update(
            created[0].id,
            ItemPatch(note="item zero updated"),
            expected_revision=created[0].revision,
        )
        app = FrictionTui(service, database_path=tmp_path / "navigation.db")
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            table = app.query_one(ItemTable)
            detail = app.query_one(DetailPane)

            app.action_last_item()
            assert table.cursor_row == table.row_count - 1
            app.action_previous_item()
            app.action_half_page_up()
            assert table.cursor_row == 0
            app.action_half_page_down()
            assert table.cursor_row == table.row_count - 1
            app.action_next_item()
            app.action_first_item()
            assert table.cursor_row == 0
            table.move_cursor(row=1)
            selected = table.selected_id
            app.refresh_items()
            await pilot.pause(0.1)
            assert table.selected_id == selected

            app.action_focus_detail()
            await pilot.pause()
            assert app.focused is not None
            assert app.focused.id == "detail-scroll"
            app.action_focus_table()
            await pilot.pause()
            assert app.focused is not None
            assert app.focused.id == "item-table"

            app.action_prefix_g()
            app.action_prefix_g()
            app._clear_prefix()
            await pilot.press("g", "x")
            assert "Unknown sequence" in str(
                app.query_one("#status-line", Static).render()
            )
            await pilot.press("z", "x")

            app._move_command_history(-1)
            app.action_command()
            app._execute_command("")
            app.action_command()
            app._execute_command("unknown")
            assert "Unknown command" in str(
                app.query_one("#status-line", Static).render()
            )
            app._command_history = [f"command-{index}" for index in range(50)]
            app.action_command()
            app._execute_command("still-unknown")
            assert len(app._command_history) == 50
            app.action_command()
            await pilot.pause()
            command = app.query_one("#command-line", Input)
            app.on_key(events.Key("k", "k"))
            assert command.value == "still-unknown"
            app.on_key(events.Key("j", "j"))
            assert command.value == ""
            app.action_escape()

            app.on_resize(events.Resize(Size(80, 24), Size(80, 24)))
            assert app.screen.has_class("narrow")
            app.on_resize(events.Resize(Size(120, 30), Size(120, 30)))
            assert not app.screen.has_class("narrow")

            app.action_help()
            await pilot.pause()
            help_screen = app.screen
            assert isinstance(help_screen, HelpScreen)
            help_screen.action_close()
            await pilot.pause()

            item = app._selected_item()
            assert item is not None
            history = service.events(item.id)
            detail.show_item(item)
            assert "history: loading" in str(detail.render())
            detail.show_item(item, [])
            assert "history: -" in str(detail.render())
            detail.show_item(item, history, show_event_payloads=False)
            detail.show_item(item, history, show_event_payloads=True)
            assert "history:" in str(detail.render())

            appended = service.create(CreateItem(note="appended row"))
            table.append_items([appended])
            assert table.row_count == 4
            table.clear()
            assert table.selected_id is None

    asyncio.run(scenario())


def test_tui_revision_conflict_does_not_retry_and_lifecycle_uses_displayed_revision(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = tmp_path / "conflict.db"
        service = create_service(database)
        created = service.create(CreateItem(note="stale display"))
        app = FrictionTui(service, database_path=database)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            service.update(
                created.id,
                ItemPatch(note="external edit"),
                expected_revision=created.revision,
            )

            app._mutate_selected("done")
            await pilot.pause(0.2)
            conflicted = service.get(created.id)
            assert conflicted.status is ItemStatus.OPEN
            assert conflicted.revision == 2

            app._mutate_selected("done")
            await pilot.pause(0.2)
            done = service.get(created.id)
            assert done.status is ItemStatus.DONE
            assert done.revision == 3

            app.action_toggle_archive()
            await pilot.pause()
            second_confirmation = app.screen
            assert isinstance(second_confirmation, ConfirmScreen)
            second_confirmation.action_yes()
            await pilot.pause(0.2)
            assert service.get(created.id).archived_at is not None

    asyncio.run(scenario())


def test_tui_paginates_at_last_row_and_never_polls(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "pagination.db"
        service = create_service(database)
        for index in range(101):
            service.create(CreateItem(note=f"item {index:03d}"))
        list_calls = 0
        original_list = service.list

        def counted_list(query: ItemQuery | None = None) -> list[FrictionItem]:
            nonlocal list_calls
            list_calls += 1
            return original_list(query)

        service.list = counted_list  # type: ignore[method-assign]
        app = FrictionTui(service, database_path=database)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            table = app.query_one(ItemTable)
            assert table.row_count == 100
            initial_calls = list_calls
            await pilot.pause(0.2)
            assert list_calls == initial_calls

            table.move_cursor(row=99)
            await pilot.pause(0.3)
            assert table.row_count == 101
            assert len(app.items) == len({item.id for item in app.items})

    asyncio.run(scenario())


def test_tui_search_applies_on_enter_and_explicit_reload_sees_external_write(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = tmp_path / "reload.db"
        service = create_service(database)
        service.create(CreateItem(note="clipboard formatting"))
        service.create(CreateItem(note="terminal startup"))
        app = FrictionTui(service, database_path=database)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            table = app.query_one(ItemTable)
            assert table.row_count == 2

            await pilot.press("/")
            search = app.query_one("#search-line", Input)
            search.value = "clipboard"
            await pilot.pause()
            assert table.row_count == 2
            await pilot.press("enter")
            await pilot.pause(0.1)
            assert table.row_count == 1

            service.create(CreateItem(note="clipboard external write"))
            await pilot.pause(0.1)
            assert table.row_count == 1
            await pilot.press(":", "e", "enter")
            await pilot.pause(0.1)
            assert table.row_count == 2

    asyncio.run(scenario())


def test_tui_add_form_persists_and_vim_prefixes_navigate(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "forms.db"
        service = create_service(database)
        service.create(CreateItem(note="first"))
        service.create(CreateItem(note="second"))
        app = FrictionTui(service, database_path=database, launch_cwd=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            table = app.query_one(ItemTable)
            await pilot.press("j")
            assert table.cursor_row == 1
            await pilot.press("g", "g")
            assert table.cursor_row == 0

            await pilot.press("a")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, ItemFormScreen)
            form.query_one("#form-note", TextArea).text = "created from tui"
            form.query_one("#form-metadata", TextArea).text = '{"team":"local"}'
            form.submit()
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ItemFormScreen)
            created = service.search("created from tui")[0]
            assert created.metadata == {"team": "local", "interface": "tui"}

    asyncio.run(scenario())


def test_tui_filter_screen_validates_navigates_applies_and_clears(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = create_service(tmp_path / "filters.db")
        service.create(
            CreateItem(
                note="matching item", tags=("editor",), git_repo="friction"
            )
        )
        service.create(CreateItem(note="other item"))
        app = FrictionTui(service, database_path=tmp_path / "filters.db")
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.action_filters()
            await pilot.pause()
            first_filters = app.screen
            assert isinstance(first_filters, FilterScreen)

            app.refresh_items()
            assert "Close the open dialog" in str(
                app.query_one("#status-line", Static).render()
            )
            first_filters.action_next_field()
            first_filters.action_previous_field()
            first_filters.action_edit_field()
            first_filters.action_cancel()
            assert first_filters._editing is False
            first_filters.action_command()
            filter_command = first_filters.query_one("#filter-command", Input)
            first_filters.on_input_submitted(
                Input.Submitted(filter_command, "not-a-command")
            )
            assert "Form commands" in str(
                first_filters.query_one("#filter-error", Static).render()
            )

            first_filters.query_one("#filter-statuses", Input).value = "unknown"
            first_filters.action_submit()
            assert isinstance(app.screen, FilterScreen)
            assert "known status" in str(
                first_filters.query_one("#filter-error", Static).render()
            )
            first_filters.query_one("#filter-search", Input).value = "matching"
            first_filters.query_one("#filter-statuses", Input).value = "open"
            first_filters.query_one("#filter-sources", Input).value = "cli"
            first_filters.query_one("#filter-repo", Input).value = "friction"
            first_filters.query_one("#filter-tags", Input).value = "editor"
            first_filters.query_one("#filter-archive", Input).value = "all"
            first_filters.on_input_submitted(
                Input.Submitted(filter_command, ":wq")
            )
            await pilot.pause(0.1)
            assert app.query_state.search_text == "matching"
            assert app.query_state.archive is ArchiveFilter.ALL
            assert app.query_one(ItemTable).row_count == 1

            app.action_filters()
            await pilot.pause()
            clear_filters = app.screen
            assert isinstance(clear_filters, FilterScreen)
            clear = clear_filters.query_one("#filter-clear", Button)
            clear_filters.on_button_pressed(Button.Pressed(clear))
            await pilot.pause(0.1)
            assert app.query_state == QueryState()

            app.action_filters()
            await pilot.pause()
            cancel_filters = app.screen
            assert isinstance(cancel_filters, FilterScreen)
            cancel = cancel_filters.query_one("#filter-cancel", Button)
            cancel_filters.on_button_pressed(Button.Pressed(cancel))
            await pilot.pause()

    asyncio.run(scenario())


def test_tui_item_form_validation_vim_commands_git_refresh_and_dirty_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        service = create_service(tmp_path / "form-validation.db")
        app = FrictionTui(
            service,
            database_path=tmp_path / "form-validation.db",
            launch_cwd=tmp_path,
        )
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.action_add()
            await pilot.pause()
            form = app.screen
            assert isinstance(form, ItemFormScreen)

            form.action_next_field()
            form.action_previous_field()
            form.action_edit_field()
            form.action_cancel()
            assert form._editing is False
            form.submit()
            assert "Note must not be empty" in str(
                form.query_one("#form-error", Static).render()
            )

            form.query_one("#form-note", TextArea).text = "validated item"
            form.query_one("#form-line", Input).value = "bad"
            form.submit()
            assert "Line must be a positive integer" in str(
                form.query_one("#form-error", Static).render()
            )
            form.query_one("#form-line", Input).value = "2"
            form.query_one("#form-column", Input).value = "3"
            form.query_one("#form-metadata", TextArea).text = "[]"
            form.submit()
            assert "Metadata must be one JSON object" in str(
                form.query_one("#form-error", Static).render()
            )
            form.query_one("#form-metadata", TextArea).text = "not-json"
            form.submit()
            assert "Expecting value" in str(
                form.query_one("#form-error", Static).render()
            )

            form.action_command()
            form_command = form.query_one("#form-command", Input)
            form.on_input_submitted(Input.Submitted(form_command, ":invalid"))
            assert "Form commands" in str(
                form.query_one("#form-error", Static).render()
            )
            form.on_input_submitted(
                Input.Submitted(form.query_one("#form-tags", Input), "")
            )
            assert form._editing is False

            form.query_one("#form-cwd", Input).value = ""
            form.refresh_git_context()
            assert "Working directory is required" in str(
                form.query_one("#form-error", Static).render()
            )
            form.query_one("#form-cwd", Input).value = str(tmp_path)
            form.query_one("#form-git-repo", Input).value = "keep-explicit"
            monkeypatch.setattr(
                "friction.interfaces.tui.screens.git_context",
                lambda _cwd: {
                    "git_root": str(tmp_path),
                    "git_repo": "discovered",
                    "git_branch": "main",
                    "git_commit": "abc123",
                },
            )
            refresh = form.query_one("#form-refresh-git", Button)
            form.on_button_pressed(Button.Pressed(refresh))
            assert form.query_one("#form-git-repo", Input).value == "keep-explicit"
            assert form.query_one("#form-git-branch", Input).value == "main"

            form.query_one("#form-metadata", TextArea).text = '{"kind":"test"}'
            form.action_submit()
            await pilot.pause(0.2)
            saved = service.search("validated item")[0]
            assert saved.line == 2
            assert saved.column == 3

            app.action_add()
            await pilot.pause()
            dirty_screen = app.screen
            assert isinstance(dirty_screen, ItemFormScreen)
            dirty_form = dirty_screen
            dirty_form.query_one("#form-note", TextArea).text = "unsaved"
            await pilot.pause()
            assert dirty_form.dirty
            dirty_form.request_cancel()
            await pilot.pause()
            confirmation = app.screen
            assert isinstance(confirmation, ConfirmScreen)
            confirmation.action_no()
            await pilot.pause()
            assert app.screen is dirty_form
            dirty_form.request_cancel()
            await pilot.pause()
            second_confirmation = app.screen
            assert isinstance(second_confirmation, ConfirmScreen)
            second_confirmation.action_yes()
            await pilot.pause()
            assert app.screen is not dirty_form

    asyncio.run(scenario())


def test_tui_edit_conflict_keeps_draft_then_reloads_and_saves_latest(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = create_service(tmp_path / "edit-conflict.db")
        created = service.create(
            CreateItem(
                note="original",
                path="original.py",
                tags=("before",),
                metadata={"version": 1},
            )
        )
        app = FrictionTui(service, database_path=tmp_path / "edit-conflict.db")
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.action_edit()
            await pilot.pause()
            form = app.screen
            assert isinstance(form, ItemFormScreen)
            service.update(
                created.id,
                ItemPatch(note="external", tags=("latest",)),
                expected_revision=created.revision,
            )
            form.query_one("#form-note", TextArea).text = "my stale draft"
            form.submit()
            await pilot.pause(0.2)
            assert app.screen is form
            assert isinstance(form, ItemFormScreen)
            assert "revision_conflict" in str(
                form.query_one("#form-error", Static).render()
            )
            assert form.query_one("#form-conflict-actions", Horizontal).display
            assert form.query_one("#form-note", TextArea).text == "my stale draft"

            reload_button = form.query_one("#form-reload", Button)
            form.on_button_pressed(Button.Pressed(reload_button))
            await pilot.pause(0.2)
            assert form.expected_revision == 2
            assert form.query_one("#form-note", TextArea).text == "external"
            assert not form.query_one("#form-conflict-actions", Horizontal).display
            assert not form.dirty

            form.query_one("#form-note", TextArea).text = "saved after reload"
            form.query_one("#form-tags", Input).value = "latest,edited"
            form.submit()
            await pilot.pause(0.2)
            saved = service.get(created.id)
            assert saved.note == "saved after reload"
            assert saved.revision == 3

            app.action_edit()
            await pilot.pause()
            second_screen = app.screen
            assert isinstance(second_screen, ItemFormScreen)
            second_form = second_screen
            second_form.show_error("recoverable")
            second_form.show_conflict("conflict")
            conflict_cancel = second_form.query_one("#form-conflict-cancel", Button)
            second_form.on_button_pressed(Button.Pressed(conflict_cancel))
            await pilot.pause()

    asyncio.run(scenario())


def test_tui_lifecycle_source_opening_and_recoverable_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        source = tmp_path / "source.py"
        source.write_text("print('local')\n", encoding="utf-8")
        service = create_service(tmp_path / "actions.db")
        created = service.create(
            CreateItem(note="action item", path=str(source), line=4, column=2)
        )
        app = FrictionTui(service, database_path=tmp_path / "actions.db")
        app.query_state = QueryState(archive=ArchiveFilter.ALL)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app._mutation_busy = True
            app._mutate_selected("done")
            assert "already running" in str(
                app.query_one("#status-line", Static).render()
            )
            app._mutation_busy = False

            app._mutate_selected("dismiss")
            await pilot.pause(0.2)
            assert service.get(created.id).status is ItemStatus.DISMISSED
            app._mutate_selected("dismiss")
            assert "Cannot change" in str(
                app.query_one("#status-line", Static).render()
            )
            app._mutate_selected("reopen")
            await pilot.pause(0.2)
            assert service.get(created.id).status is ItemStatus.OPEN
            app._mutate_selected("reopen")
            assert "Cannot change" in str(
                app.query_one("#status-line", Static).render()
            )

            app._mutate_selected("archive")
            await pilot.pause(0.2)
            assert service.get(created.id).archived_at is not None
            app._mutate_selected("archive")
            assert "already archived" in str(
                app.query_one("#status-line", Static).render()
            )
            app.action_toggle_archive()
            await pilot.pause(0.2)
            assert service.get(created.id).archived_at is None
            app._mutate_selected("unarchive")
            assert "not archived" in str(
                app.query_one("#status-line", Static).render()
            )

            opened: list[tuple[Path, int | None, int | None]] = []
            monkeypatch.setattr(app, "suspend", lambda: nullcontext())
            monkeypatch.setattr(
                tui_app_module,
                "launch_editor",
                lambda target, *, line, column: opened.append(
                    (target, line, column)
                ),
            )
            app.action_open_source()
            await pilot.pause(0.1)
            assert opened == [(source, 4, 2)]

            monkeypatch.setattr(
                tui_app_module,
                "resolved_source",
                lambda _item: (_ for _ in ()).throw(EditorError("unavailable")),
            )
            app.action_open_source()
            assert "validation_error" in str(
                app.query_one("#status-line", Static).render()
            )

            original_mark_done = service.mark_done

            def broken_mark_done(*_args: object, **_kwargs: object) -> FrictionItem:
                raise RuntimeError("write failed")

            service.mark_done = broken_mark_done  # type: ignore[method-assign]
            app._mutate_selected("done")
            await pilot.pause(0.2)
            assert "storage_error: write failed" in str(
                app.query_one("#status-line", Static).render()
            )
            service.mark_done = original_mark_done  # type: ignore[method-assign]
            app._mutation("invalid", created.id, service.get(created.id).revision)
            await pilot.pause(0.2)
            assert "storage_error" in str(
                app.query_one("#status-line", Static).render()
            )

    asyncio.run(scenario())


def test_tui_storage_errors_generation_guards_and_missing_selection(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = create_service(tmp_path / "errors.db")
        original_list = service.list

        def broken_list(_query: ItemQuery | None = None) -> list[FrictionItem]:
            raise RuntimeError("database unavailable")

        service.list = broken_list  # type: ignore[method-assign, assignment]
        app = FrictionTui(service, database_path=tmp_path / "errors.db")
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            banner = app.query_one("#fatal-banner", Static)
            assert banner.display
            assert "database unavailable" in str(banner.render())
            app._query_failed(app.generation - 1, RuntimeError("stale"))
            app._query_loaded(app.generation - 1, [], None, False)

            service.list = original_list  # type: ignore[method-assign]
            first = service.create(CreateItem(note="first"))
            second = service.create(CreateItem(note="second"))
            app.refresh_items()
            await pilot.pause(0.2)
            assert not banner.display

            app._query_loaded(app.generation, [second], first.id, False)
            assert "no longer matches" in str(
                app.query_one("#status-line", Static).render()
            )
            app._history_loaded(app._detail_generation - 1, second.id, [])
            app._history_loaded(app._detail_generation, first.id, [])
            app.has_more = False
            app._load_next_page()
            app._filters_applied(None)

            app.query_one(ItemTable).clear()
            app.items = []
            app._items_by_id = {}
            app.action_edit()
            app.action_open_source()
            app.action_toggle_archive()
            app._mutate_selected("done")
            assert "Select an item" in str(
                app.query_one("#status-line", Static).render()
            )

    asyncio.run(scenario())
