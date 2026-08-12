from pathlib import Path

import pytest

from friction.application import ArchiveFilter
from friction.domain import CreateItem, ItemSource, ItemStatus, RevisionConflictError
from friction.interfaces.mcp import operations
from friction.storage import create_service


def test_mcp_add_forces_source_and_list_search_paginate(tmp_path: Path) -> None:
    service = create_service(tmp_path / "operations.db")
    first = operations.add_item(
        service,
        note="clipboard formatting",
        tags=("editor",),
        metadata={"client": "test"},
    )
    service.create(
        CreateItem(
            note="terminal formatting",
            source=ItemSource.CLI,
            tags=("shell",),
        )
    )

    page = operations.list_items(service, limit=1)
    searched = operations.search_items(
        service, query_text="clipboard", sources=(ItemSource.MCP,)
    )

    assert first.source is ItemSource.MCP
    assert first.metadata == {"client": "test"}
    assert page.count == 1
    assert page.has_more
    assert searched.items == [first]
    assert not searched.has_more


def test_mcp_filters_get_update_clear_lifecycle_and_history(tmp_path: Path) -> None:
    service = create_service(tmp_path / "mutations.db")
    created = operations.add_item(
        service,
        note="lifecycle item",
        path="/tmp/context.py",
        tags=("editor",),
    )
    detail = operations.get_item(
        service, identifier=str(created.id)[:8], include_history=True
    )
    updated = operations.update_item(
        service,
        identifier=str(created.id),
        revision=created.revision,
        note="updated lifecycle item",
        tags=[],
        clear_fields=("path",),
    )
    done = operations.mark_done(
        service, identifier=str(created.id), revision=updated.revision
    )
    archived = operations.archive(
        service, identifier=str(created.id), revision=done.revision
    )
    restored = operations.unarchive(
        service, identifier=str(created.id), revision=archived.revision
    )
    reopened = operations.reopen(
        service, identifier=str(created.id), revision=restored.revision
    )
    history = operations.history(service, identifier=str(created.id))
    active_page = operations.list_items(
        service, archive=ArchiveFilter.ACTIVE, statuses=(ItemStatus.OPEN,)
    )

    assert len(detail.events) == 1
    assert updated.path is None
    assert updated.tags == ()
    assert done.status is ItemStatus.DONE
    assert archived.archived_at is not None
    assert restored.archived_at is None
    assert reopened.status is ItemStatus.OPEN
    assert len(history.events) == 6
    assert active_page.items == [reopened]

    with pytest.raises(RevisionConflictError):
        operations.reopen(
            service, identifier=str(created.id), revision=updated.revision
        )

    dismissed_item = operations.add_item(service, note="dismiss separately")
    dismissed = operations.dismiss(
        service,
        identifier=str(dismissed_item.id),
        revision=dismissed_item.revision,
    )
    assert dismissed.status is ItemStatus.DISMISSED


def test_mcp_update_validation_rejects_empty_overlap_and_bad_pagination(
    tmp_path: Path,
) -> None:
    service = create_service(tmp_path / "validation.db")
    created = operations.add_item(service, note="validation item")

    with pytest.raises(operations.McpInputError):
        operations.update_item(
            service, identifier=str(created.id), revision=created.revision
        )
    with pytest.raises(operations.McpInputError):
        operations.update_item(
            service,
            identifier=str(created.id),
            revision=created.revision,
            path="/tmp/value",
            clear_fields=("path",),
        )
    with pytest.raises(operations.McpInputError):
        operations.list_items(service, limit=201)
    with pytest.raises(operations.McpInputError):
        operations.search_items(service, query_text="  ")
