from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from friction.contracts import (
    AddRequest,
    ItemData,
    UpdateRequest,
    error_envelope,
    success_envelope,
)


def test_add_request_is_versioned_and_strict() -> None:
    request = AddRequest.model_validate(
        {
            "schema_version": 1,
            "data": {
                "note": "multiline\nnote",
                "source": "nvim",
                "path": "/tmp/example.py",
                "line": 4,
                "tags": ["editor"],
            },
        }
    )

    command = request.data.to_command()
    assert command.note == "multiline\nnote"
    assert command.line == 4

    with pytest.raises(ValidationError):
        AddRequest.model_validate(
            {"schema_version": 2, "data": {"note": "unsupported"}}
        )


def test_update_request_preserves_explicit_null_fields() -> None:
    request = UpdateRequest.model_validate(
        {
            "schema_version": 1,
            "data": {"revision": 3, "path": None, "tags": []},
        }
    )

    patch = request.data.to_patch()
    assert patch.changes() == {"path": None, "tags": ()}


def test_success_and_error_envelopes_are_exclusive() -> None:
    payload = ItemData.model_validate(
        {
            "id": "12345678-1234-5678-1234-567812345678",
            "note": "test",
            "status": "open",
            "created_at": datetime(2026, 7, 16, tzinfo=UTC),
            "updated_at": datetime(2026, 7, 16, tzinfo=UTC),
            "archived_at": None,
            "source": "cli",
            "path": None,
            "line": None,
            "column": None,
            "cwd": "/tmp",
            "filetype": None,
            "git_root": None,
            "git_repo": None,
            "git_branch": None,
            "git_commit": None,
            "tags": [],
            "metadata": {},
            "revision": 1,
        }
    )

    success = success_envelope(payload)
    failure = error_envelope("not_found", "missing")

    assert success.model_dump(mode="json")["schema_version"] == 1
    assert success.error is None
    assert failure.data is None
    assert failure.error is not None
