import json
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner, Result

from friction.cli import app

FIXTURES = Path(__file__).parents[1] / "fixtures" / "jsonl"
runner = CliRunner()


def _invoke(database: Path, arguments: list[str]) -> Result:
    return runner.invoke(app, ["--db", str(database), *arguments])


def _json(result: Result) -> dict[str, Any]:
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_dry_run_does_not_create_database(tmp_path: Path) -> None:
    database = tmp_path / "missing" / "friction.db"

    result = _invoke(
        database,
        [
            "import-jsonl",
            str(FIXTURES / "legacy.jsonl"),
            "--dry-run",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _json(result)["data"]["valid_records"] == 3
    assert not database.exists()


def test_import_export_backup_and_doctor_commands(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    export_directory = tmp_path / "exports"
    backup_directory = tmp_path / "backups"

    imported = _invoke(
        database,
        ["import-jsonl", str(FIXTURES / "legacy.jsonl"), "--output", "json"],
    )
    exported = _invoke(
        database,
        ["export", "--format", "jsonl", "--output", str(export_directory)],
    )
    backed_up = _invoke(
        database,
        ["backup", str(backup_directory), "--output", "json"],
    )
    doctor = _invoke(database, ["doctor", "--output", "json"])

    assert _json(imported)["data"]["imported"] == 3
    assert exported.exit_code == 0, exported.output
    assert len(list(export_directory.glob("*.jsonl"))) == 1
    assert _json(backed_up)["data"]["size"] > 0
    assert _json(doctor)["data"]["ok"] is True


def test_invalid_file_returns_import_error_without_partial_rows(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"

    invalid = _invoke(
        database,
        ["import-jsonl", str(FIXTURES / "invalid.jsonl"), "--output", "json"],
    )
    listed = _invoke(database, ["list", "--all", "--output", "json"])

    assert invalid.exit_code == 6
    assert _json(invalid)["error"]["code"] == "import_error"
    assert _json(listed)["data"]["count"] == 0
