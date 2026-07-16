import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner, Result

from friction import cli
from friction.cli import CliInputError, app
from friction.domain import CreateItem

runner = CliRunner()


def _invoke(
    database: Path, arguments: list[str], *, stdin: str | None = None
) -> Result:
    return runner.invoke(app, ["--db", str(database), *arguments], input=stdin)


def _json(result: Result) -> dict[str, Any]:
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _add(database: Path, note: str, *options: str) -> dict[str, Any]:
    result = _invoke(database, ["add", note, *options, "--output", "json"])
    assert result.exit_code == 0, result.output
    return cast(dict[str, Any], _json(result)["data"])


def test_cli_adds_machine_input_and_filters_json(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    request = {
        "schema_version": 1,
        "data": {
            "note": "clipboard says \"no\"\nand loses formatting",
            "source": "nvim",
            "path": "/tmp/example.py",
            "line": 7,
            "tags": ["Editor", "clipboard"],
        },
    }

    added = _invoke(
        database,
        ["add", "--input-json", "-", "--output", "json"],
        stdin=json.dumps(request),
    )
    listed = _invoke(
        database,
        ["list", "--source", "nvim", "--tag", "editor", "--output", "json"],
    )
    searched = _invoke(
        database,
        ["search", "clipboard format", "--output", "json"],
    )

    assert added.exit_code == 0, added.output
    assert _json(added)["data"]["note"].endswith("loses formatting")
    assert _json(listed)["data"]["count"] == 1
    assert _json(searched)["data"]["count"] == 1


def test_cli_updates_lifecycle_and_history(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    created = _add(database, "slow command")
    identifier = created["id"]

    done = _invoke(
        database,
        ["done", identifier, "--revision", "1", "--output", "json"],
    )
    stale = _invoke(
        database,
        ["reopen", identifier, "--revision", "1", "--output", "json"],
    )
    reopened = _invoke(
        database,
        ["reopen", identifier, "--revision", "2", "--output", "json"],
    )
    update_request = {
        "schema_version": 1,
        "data": {"revision": 3, "note": "faster command", "tags": ["shell"]},
    }
    updated = _invoke(
        database,
        ["update", identifier, "--input-json", "-", "--output", "json"],
        stdin=json.dumps(update_request),
    )
    shown = _invoke(
        database,
        ["show", identifier, "--history", "--output", "json"],
    )

    assert _json(done)["data"]["revision"] == 2
    assert stale.exit_code == 4
    assert _json(stale)["error"]["code"] == "revision_conflict"
    assert _json(reopened)["data"]["revision"] == 3
    assert _json(updated)["data"]["note"] == "faster command"
    assert len(_json(shown)["data"]["events"]) == 4


def test_cli_bulk_archive_and_unarchive(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    first = _add(database, "first")
    _add(database, "second")
    _invoke(database, ["done", first["id"]])

    archived = _invoke(
        database,
        ["archive", "--status", "done", "--yes", "--output", "json"],
    )
    active = _invoke(database, ["list", "--output", "json"])
    archived_list = _invoke(
        database, ["list", "--archived", "--output", "json"]
    )
    restored = _invoke(
        database,
        ["unarchive", first["id"], "--revision", "3", "--output", "json"],
    )

    assert _json(archived)["data"]["count"] == 1
    assert _json(active)["data"]["count"] == 1
    assert _json(archived_list)["data"]["count"] == 1
    assert _json(restored)["data"]["archived_at"] is None


def test_cli_edit_and_open_use_adapter_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "friction.db"
    source = tmp_path / "example.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    created = _add(database, "before", "--path", str(source), "--line", "1")
    opened: list[tuple[Path, int | None, int | None]] = []

    monkeypatch.setattr(cli, "_edit_text", lambda _initial: "after")
    monkeypatch.setattr(
        cli,
        "_launch_editor",
        lambda target, line=None, column=None: opened.append((target, line, column)),
    )

    edited = _invoke(
        database, ["edit", created["id"], "--output", "json"]
    )
    opened_result = _invoke(database, ["open", created["id"]])

    assert _json(edited)["data"]["note"] == "after"
    assert opened_result.exit_code == 0
    assert opened == [(source.resolve(), 1, None)]


def test_cli_returns_versioned_validation_errors(tmp_path: Path) -> None:
    result = _invoke(
        tmp_path / "friction.db",
        ["add", "--input-json", "-", "--output", "json"],
        stdin="{not json}",
    )

    assert result.exit_code == 2
    assert _json(result)["schema_version"] == 1
    assert _json(result)["error"]["code"] == "validation_error"


def test_editor_chain_requires_an_executable() -> None:
    assert cli._editor_command({"EDITOR": "/usr/bin/true"}) == ["/usr/bin/true"]

    with pytest.raises(CliInputError):
        cli._editor_command({})

    with pytest.raises(CliInputError):
        cli._editor_command({"EDITOR": "/missing/friction-editor"})


def test_human_prompt_show_and_dismiss_workflow(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    prompted = _invoke(database, ["add"], stdin="prompted note\n")
    listed = _invoke(database, ["list"])
    identifier = listed.stdout.split(maxsplit=1)[0]
    dismissed = _invoke(database, ["dismiss", identifier])
    shown = _invoke(database, ["show", identifier, "--history"])
    reopened = _invoke(database, ["reopen", identifier])

    assert prompted.exit_code == 0
    assert "Created" in prompted.stdout
    assert "prompted note" in listed.stdout
    assert "Dismiss" in dismissed.stdout
    assert "status: dismissed" in shown.stdout
    assert "event:" in shown.stdout
    assert "Reopen" in reopened.stdout


def test_edit_capture_and_json_file_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "friction.db"
    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps({"schema_version": 1, "data": {"note": "from file"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_edit_text", lambda draft: f"{draft} edited".strip())

    edited = _invoke(database, ["add", "draft", "--edit", "--output", "json"])
    from_file = _invoke(
        database,
        ["add", "--input-json", str(request_file), "--output", "json"],
    )

    assert _json(edited)["data"]["note"] == "draft edited"
    assert _json(from_file)["data"]["note"] == "from file"


def test_cli_validates_archive_and_query_combinations(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    created = _add(database, "archive exactly one")

    invalid_query = _invoke(
        database,
        ["list", "--archived", "--all", "--output", "json"],
    )
    missing_target = _invoke(database, ["archive", "--output", "json"])
    conflicting_target = _invoke(
        database,
        ["archive", created["id"], "--status", "open", "--output", "json"],
    )
    archived = _invoke(
        database,
        ["archive", created["id"], "--revision", "1", "--output", "json"],
    )

    assert invalid_query.exit_code == 2
    assert missing_target.exit_code == 2
    assert conflicting_target.exit_code == 2
    assert _json(archived)["data"]["archived_at"] is not None


def test_cli_reports_missing_item_and_source(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    created = _add(database, "no source", "--path", str(tmp_path / "missing"))
    missing_item = _invoke(
        database, ["show", "deadbeef", "--output", "json"]
    )
    missing_source = _invoke(
        database, ["open", created["id"], "--output", "json"]
    )

    assert missing_item.exit_code == 3
    assert _json(missing_item)["error"]["code"] == "not_found"
    assert missing_source.exit_code == 2
    assert _json(missing_source)["error"]["code"] == "validation_error"


def test_cli_helper_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    relative = tmp_path / "relative.py"
    relative.write_text("", encoding="utf-8")
    item = CreateItem(
        note="relative", path="relative.py", cwd=str(tmp_path)
    ).to_item()

    assert cli._resolved_source(item) == relative.resolve()
    assert cli._git_context(tmp_path)["git_root"] is None
    assert cli._exit_code("not_found") == 3
    assert cli._exit_code("revision_conflict") == 4
    assert cli._exit_code("import_error") == 6
    assert cli._exit_code("storage_error") == 5

    monkeypatch.setattr(cli, "_editor_command", lambda: ["/usr/bin/false"])
    with pytest.raises(CliInputError):
        cli._launch_editor(relative)


def test_edit_text_reads_editor_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def replace_note(target: Path, **_kwargs: Any) -> None:
        target.write_text("changed in editor\n", encoding="utf-8")

    monkeypatch.setattr(cli, "_launch_editor", replace_note)

    assert cli._edit_text("initial") == "changed in editor"
