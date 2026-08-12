import asyncio
from pathlib import Path

from textual.widgets import Input, Static, TextArea

from friction.application import ItemQuery
from friction.domain import CreateItem, FrictionItem, ItemPatch, ItemStatus
from friction.interfaces.tui.app import FrictionTui
from friction.interfaces.tui.screens import ConfirmScreen, ItemFormScreen
from friction.interfaces.tui.widgets import DetailPane, ItemTable
from friction.storage import create_service


def test_tui_empty_and_narrow_main_screen(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "empty.db"
        app = FrictionTui(create_service(database), database_path=database)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.1)
            assert app.query_one(ItemTable).row_count == 0
            assert "No matching" in str(app.query_one(DetailPane).render())
            assert database.name in str(app.query_one("#title-bar", Static).render())

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
            confirmation = app.screen
            assert isinstance(confirmation, ConfirmScreen)
            confirmation.action_yes()
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
