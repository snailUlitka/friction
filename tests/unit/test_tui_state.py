from pathlib import Path

from friction.application import ArchiveFilter
from friction.domain import CreateItem, ItemSource, ItemStatus
from friction.interfaces.tui.screens import ItemFormValues, QueryState


def test_query_state_builds_complete_paginated_query() -> None:
    state = QueryState(
        search_text="clipboard",
        statuses=(ItemStatus.OPEN,),
        sources=(ItemSource.EMACS,),
        repo="friction",
        tags=("editor",),
        archive=ArchiveFilter.ALL,
    )

    query = state.item_query(limit=100, offset=200)

    assert query.statuses == (ItemStatus.OPEN,)
    assert query.sources == (ItemSource.EMACS,)
    assert query.repo == "friction"
    assert query.tags == ("editor",)
    assert query.archive is ArchiveFilter.ALL
    assert query.limit == 100
    assert query.offset == 200
    assert "/clipboard" in state.summary


def test_form_values_force_tui_attribution_and_build_sparse_patch(
    tmp_path: Path,
) -> None:
    original = CreateItem(
        note="before",
        path=str(tmp_path / "before.py"),
        metadata={"owner": "local"},
    ).to_item()
    values = ItemFormValues(
        note="after",
        tags=(),
        path=None,
        line=None,
        column=None,
        cwd=None,
        filetype=None,
        git_root=None,
        git_repo=None,
        git_branch=None,
        git_commit=None,
        metadata={"owner": "local"},
    )

    command = values.create_command()
    patch = values.patch_against(original)

    assert command.source is ItemSource.CLI
    assert command.metadata == {"owner": "local", "interface": "tui"}
    assert patch.changes() == {"note": "after", "path": None}
