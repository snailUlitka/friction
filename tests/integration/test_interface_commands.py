from pathlib import Path

import pytest
from typer.testing import CliRunner

from friction.cli import app
from friction.interfaces import tui as tui_adapter
from friction.interfaces.tui.app import FrictionTui
from friction.storage import create_sqlite_engine, current_revision

runner = CliRunner()


def test_tui_command_passes_root_database_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "explicit.db"
    received: list[Path | None] = []
    monkeypatch.setattr(tui_adapter, "run_tui", received.append)

    result = runner.invoke(app, ["--db", str(database), "tui"])

    assert result.exit_code == 0, result.output
    assert received == [database]


def test_tui_entry_point_migrates_before_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "fresh.db"
    monkeypatch.setattr(FrictionTui, "run", lambda _self: None)

    tui_adapter.run_tui(database)

    assert current_revision(create_sqlite_engine(database)) == "0001_initial"
