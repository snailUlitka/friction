from pathlib import Path

import pytest

from friction.interfaces import context


def test_git_context_is_best_effort_when_git_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(context, "_git_value", lambda *_args: None)

    assert context.git_context(tmp_path) == {
        "git_root": None,
        "git_repo": None,
        "git_branch": None,
        "git_commit": None,
    }


def test_git_context_keeps_detached_head_as_no_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    def git_value(_cwd: Path, *arguments: str) -> str | None:
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(root)
        if arguments == ("branch", "--show-current"):
            return None
        return "123456"

    monkeypatch.setattr(context, "_git_value", git_value)

    assert context.git_context(root) == {
        "git_root": str(root),
        "git_repo": "project",
        "git_branch": None,
        "git_commit": "123456",
    }


def test_missing_git_context_preserves_explicit_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        context,
        "git_context",
        lambda _cwd: {
            "git_root": "/root",
            "git_repo": "repo",
            "git_branch": "main",
            "git_commit": "abc",
        },
    )

    assert context.missing_git_context(
        tmp_path, supplied_fields={"git_repo", "git_branch"}
    ) == {"git_root": "/root", "git_commit": "abc"}
    assert context.missing_git_context(None) == {}
