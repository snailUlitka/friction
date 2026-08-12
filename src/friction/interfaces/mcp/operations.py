"""Service-backed MCP operations independent of SDK registration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import JsonValue

from friction.application import ArchiveFilter, FrictionService, ItemQuery
from friction.contracts import EventData, ItemData
from friction.domain import (
    CreateItem,
    FrictionError,
    ItemPatch,
    ItemSource,
    ItemStatus,
)
from friction.interfaces.context import GIT_CONTEXT_FIELDS, missing_git_context
from friction.interfaces.mcp.models import McpEventHistory, McpItemDetail, McpItemPage

ClearableField = Literal[
    "path",
    "line",
    "column",
    "cwd",
    "filetype",
    "git_root",
    "git_repo",
    "git_branch",
    "git_commit",
]

CLEARABLE_FIELDS = frozenset(
    {
        "path",
        "line",
        "column",
        "cwd",
        "filetype",
        *GIT_CONTEXT_FIELDS,
    }
)


class McpInputError(FrictionError):
    """Stable MCP adapter validation error."""

    code = "validation_error"


def _query(
    *,
    statuses: Iterable[ItemStatus] = (),
    sources: Iterable[ItemSource] = (),
    repo: str | None = None,
    tags: Iterable[str] = (),
    archive: ArchiveFilter = ArchiveFilter.ACTIVE,
    limit: int = 50,
    offset: int = 0,
) -> ItemQuery:
    if not 1 <= limit <= 200:
        raise McpInputError("limit must be between 1 and 200.")
    if offset < 0:
        raise McpInputError("offset must not be negative.")
    return ItemQuery(
        statuses=tuple(statuses),
        sources=tuple(sources),
        repo=repo,
        tags=tuple(tags),
        archive=archive,
        limit=limit + 1,
        offset=offset,
    )


def _page(items: list[Any], *, limit: int, offset: int) -> McpItemPage:
    page_items = items[:limit]
    return McpItemPage(
        items=[ItemData.from_domain(item) for item in page_items],
        count=len(page_items),
        limit=limit,
        offset=offset,
        has_more=len(items) > limit,
    )


def add_item(
    service: FrictionService,
    *,
    note: str,
    path: str | None = None,
    line: int | None = None,
    column: int | None = None,
    cwd: str | None = None,
    filetype: str | None = None,
    git_root: str | None = None,
    git_repo: str | None = None,
    git_branch: str | None = None,
    git_commit: str | None = None,
    tags: Iterable[str] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ItemData:
    """Create one MCP-attributed item with best-effort Git enrichment."""
    context = {
        "git_root": git_root,
        "git_repo": git_repo,
        "git_branch": git_branch,
        "git_commit": git_commit,
    }
    supplied = {field for field, value in context.items() if value is not None}
    context.update(missing_git_context(cwd, supplied_fields=supplied))
    command = CreateItem(
        note=note,
        source=ItemSource.MCP,
        path=path,
        line=line,
        column=column,
        cwd=cwd,
        filetype=filetype,
        git_root=context["git_root"],
        git_repo=context["git_repo"],
        git_branch=context["git_branch"],
        git_commit=context["git_commit"],
        tags=tuple(tags),
        metadata=metadata or {},
    )
    return ItemData.from_domain(service.create(command))


def list_items(
    service: FrictionService,
    *,
    statuses: Iterable[ItemStatus] = (),
    sources: Iterable[ItemSource] = (),
    repo: str | None = None,
    tags: Iterable[str] = (),
    archive: ArchiveFilter = ArchiveFilter.ACTIVE,
    limit: int = 50,
    offset: int = 0,
) -> McpItemPage:
    query = _query(
        statuses=statuses,
        sources=sources,
        repo=repo,
        tags=tags,
        archive=archive,
        limit=limit,
        offset=offset,
    )
    return _page(service.list(query), limit=limit, offset=offset)


def search_items(
    service: FrictionService,
    *,
    query_text: str,
    statuses: Iterable[ItemStatus] = (),
    sources: Iterable[ItemSource] = (),
    repo: str | None = None,
    tags: Iterable[str] = (),
    archive: ArchiveFilter = ArchiveFilter.ACTIVE,
    limit: int = 50,
    offset: int = 0,
) -> McpItemPage:
    text = query_text.strip()
    if not text:
        raise McpInputError("query must not be blank.")
    item_query = _query(
        statuses=statuses,
        sources=sources,
        repo=repo,
        tags=tags,
        archive=archive,
        limit=limit,
        offset=offset,
    )
    return _page(service.search(text, item_query), limit=limit, offset=offset)


def get_item(
    service: FrictionService, *, identifier: str, include_history: bool = False
) -> McpItemDetail:
    item = service.get(identifier)
    events = service.events(item.id) if include_history else []
    return McpItemDetail(
        item=ItemData.from_domain(item),
        events=[EventData.from_domain(event) for event in events],
    )


def update_item(
    service: FrictionService,
    *,
    identifier: str,
    revision: int,
    note: str | None = None,
    path: str | None = None,
    line: int | None = None,
    column: int | None = None,
    cwd: str | None = None,
    filetype: str | None = None,
    git_root: str | None = None,
    git_repo: str | None = None,
    git_branch: str | None = None,
    git_commit: str | None = None,
    tags: Iterable[str] | None = None,
    metadata: dict[str, JsonValue] | None = None,
    clear_fields: Iterable[ClearableField] = (),
) -> ItemData:
    if revision < 1:
        raise McpInputError("revision must be positive.")
    supplied: dict[str, Any] = {
        key: value
        for key, value in {
            "note": note,
            "path": path,
            "line": line,
            "column": column,
            "cwd": cwd,
            "filetype": filetype,
            "git_root": git_root,
            "git_repo": git_repo,
            "git_branch": git_branch,
            "git_commit": git_commit,
            "tags": tuple(tags) if tags is not None else None,
            "metadata": metadata,
        }.items()
        if value is not None
    }
    fields_to_clear = set(clear_fields)
    unknown = fields_to_clear - CLEARABLE_FIELDS
    if unknown:
        raise McpInputError(
            "clear_fields contains unsupported fields.",
            details={"fields": sorted(unknown)},
        )
    overlap = fields_to_clear & supplied.keys()
    if overlap:
        raise McpInputError(
            "A field cannot be supplied and cleared in the same update.",
            details={"fields": sorted(overlap)},
        )
    supplied.update(dict.fromkeys(fields_to_clear))
    if not supplied:
        raise McpInputError("At least one update or clear operation is required.")
    patch = ItemPatch.model_validate(supplied)
    return ItemData.from_domain(
        service.update(identifier, patch, expected_revision=revision)
    )


def _lifecycle(
    service: FrictionService, *, action: str, identifier: str, revision: int
) -> ItemData:
    if revision < 1:
        raise McpInputError("revision must be positive.")
    operation = {
        "done": service.mark_done,
        "dismiss": service.dismiss,
        "reopen": service.reopen,
        "archive": service.archive,
        "unarchive": service.unarchive,
    }[action]
    return ItemData.from_domain(operation(identifier, expected_revision=revision))


def mark_done(service: FrictionService, *, identifier: str, revision: int) -> ItemData:
    return _lifecycle(service, action="done", identifier=identifier, revision=revision)


def dismiss(service: FrictionService, *, identifier: str, revision: int) -> ItemData:
    return _lifecycle(
        service, action="dismiss", identifier=identifier, revision=revision
    )


def reopen(service: FrictionService, *, identifier: str, revision: int) -> ItemData:
    return _lifecycle(
        service, action="reopen", identifier=identifier, revision=revision
    )


def archive(service: FrictionService, *, identifier: str, revision: int) -> ItemData:
    return _lifecycle(
        service, action="archive", identifier=identifier, revision=revision
    )


def unarchive(service: FrictionService, *, identifier: str, revision: int) -> ItemData:
    return _lifecycle(
        service, action="unarchive", identifier=identifier, revision=revision
    )


def history(service: FrictionService, *, identifier: str) -> McpEventHistory:
    item = service.get(identifier)
    return McpEventHistory(
        item_id=item.id,
        events=[EventData.from_domain(event) for event in service.events(item.id)],
    )
