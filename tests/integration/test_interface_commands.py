import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from friction.cli import app
from friction.interfaces import mcp as mcp_adapter
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


def test_mcp_command_passes_root_database_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "mcp-explicit.db"
    received: list[Path | None] = []
    monkeypatch.setattr(mcp_adapter, "run_mcp", received.append)

    result = runner.invoke(app, ["--db", str(database), "mcp"])

    assert result.exit_code == 0, result.output
    assert received == [database]


def test_mcp_entry_point_migrates_and_uses_only_stdio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "mcp-fresh.db"
    transports: list[str] = []

    class Server:
        def run(self, transport: str) -> None:
            transports.append(transport)

    monkeypatch.setattr(mcp_adapter, "create_mcp_server", lambda _service: Server())

    mcp_adapter.run_mcp(database)

    assert current_revision(create_sqlite_engine(database)) == "0001_initial"
    assert transports == ["stdio"]


def test_importing_mcp_adapter_does_not_touch_database(tmp_path: Path) -> None:
    database = tmp_path / "must-not-exist.db"
    environment = os.environ.copy()
    environment["FRICTION_DB_PATH"] = str(database)

    result = subprocess.run(
        [sys.executable, "-c", "import friction.interfaces.mcp"],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not database.exists()
