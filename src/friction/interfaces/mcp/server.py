"""FastMCP stdio registration over pure Friction operations."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, JsonValue, ValidationError

from friction.application import ArchiveFilter, FrictionService
from friction.contracts import ApiError, EventData, ItemData
from friction.domain import FrictionError, ItemSource, ItemStatus
from friction.interfaces.mcp import operations

logger = logging.getLogger(__name__)

TOOL_NAMES = (
    "friction_add",
    "friction_list",
    "friction_search",
    "friction_get",
    "friction_update",
    "friction_mark_done",
    "friction_dismiss",
    "friction_reopen",
    "friction_archive",
    "friction_unarchive",
    "friction_history",
)


def _tool_result(operation: Callable[[], BaseModel]) -> CallToolResult:
    try:
        result = operation()
    except FrictionError as error:
        api_error = ApiError(
            code=error.code,
            message=error.message,
            details=error.details,
        )
        payload = api_error.model_dump(mode="json")
        return CallToolResult(
            content=[TextContent(type="text", text=f"{error.code}: {error.message}")],
            structuredContent=payload,
            isError=True,
        )
    except ValidationError as error:
        api_error = ApiError(
            code="validation_error",
            message="Input does not match the Friction contract.",
            details={"errors": json.loads(error.json(include_url=False))},
        )
        payload = api_error.model_dump(mode="json")
        return CallToolResult(
            content=[TextContent(type="text", text="validation_error: invalid input")],
            structuredContent=payload,
            isError=True,
        )
    except Exception:
        logger.exception("Unexpected MCP operation failure")
        api_error = ApiError(
            code="storage_error",
            message="The local Friction store could not complete the operation.",
            details={},
        )
        return CallToolResult(
            content=[TextContent(type="text", text="storage_error: operation failed")],
            structuredContent=api_error.model_dump(mode="json"),
            isError=True,
        )
    payload = result.model_dump(mode="json")
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structuredContent=payload,
    )


def _resource_result(operation: Callable[[], BaseModel]) -> str:
    try:
        result = operation()
    except FrictionError as error:
        raise ValueError(f"{error.code}: {error.message}") from error
    return result.model_dump_json()


def create_mcp_server(service: FrictionService) -> FastMCP[None]:
    """Create one local-only MCP server without touching storage at import time."""
    server: FastMCP[None] = FastMCP(
        "friction",
        instructions=(
            "Inspect and manage private local workflow-friction items. "
            "Every mutation requires the revision returned by a read operation."
        ),
        log_level="WARNING",
    )

    @server.tool(
        name="friction_add",
        description=(
            "Create an open MCP-attributed item and return its canonical state."
        ),
    )
    def friction_add(
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
        tags: list[str] | None = None,
        metadata: dict[str, JsonValue] | None = None,
    ) -> CallToolResult:
        return _tool_result(
            lambda: operations.add_item(
                service,
                note=note,
                path=path,
                line=line,
                column=column,
                cwd=cwd,
                filetype=filetype,
                git_root=git_root,
                git_repo=git_repo,
                git_branch=git_branch,
                git_commit=git_commit,
                tags=tags or (),
                metadata=metadata,
            )
        )

    @server.tool(
        name="friction_list",
        description=(
            "List deterministic pages; limit is 1-200 and archive defaults active."
        ),
    )
    def friction_list(
        statuses: list[ItemStatus] | None = None,
        sources: list[ItemSource] | None = None,
        repo: str | None = None,
        tags: list[str] | None = None,
        archive: ArchiveFilter = ArchiveFilter.ACTIVE,
        limit: int = 50,
        offset: int = 0,
    ) -> CallToolResult:
        return _tool_result(
            lambda: operations.list_items(
                service,
                statuses=statuses or (),
                sources=sources or (),
                repo=repo,
                tags=tags or (),
                archive=archive,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="friction_search",
        description=(
            "Full-text search in relevance order with list filters and pagination."
        ),
    )
    def friction_search(
        query: str,
        statuses: list[ItemStatus] | None = None,
        sources: list[ItemSource] | None = None,
        repo: str | None = None,
        tags: list[str] | None = None,
        archive: ArchiveFilter = ArchiveFilter.ACTIVE,
        limit: int = 50,
        offset: int = 0,
    ) -> CallToolResult:
        return _tool_result(
            lambda: operations.search_items(
                service,
                query_text=query,
                statuses=statuses or (),
                sources=sources or (),
                repo=repo,
                tags=tags or (),
                archive=archive,
                limit=limit,
                offset=offset,
            )
        )

    @server.tool(
        name="friction_get",
        description=(
            "Resolve a UUID or unique prefix; optionally return complete history."
        ),
    )
    def friction_get(identifier: str, include_history: bool = False) -> CallToolResult:
        return _tool_result(
            lambda: operations.get_item(
                service, identifier=identifier, include_history=include_history
            )
        )

    @server.tool(
        name="friction_update",
        description=(
            "Patch non-lifecycle fields using the required current revision. "
            "Use clear_fields for nullable context fields; stale writes fail."
        ),
    )
    def friction_update(
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
        tags: list[str] | None = None,
        metadata: dict[str, JsonValue] | None = None,
        clear_fields: list[operations.ClearableField] | None = None,
    ) -> CallToolResult:
        return _tool_result(
            lambda: operations.update_item(
                service,
                identifier=identifier,
                revision=revision,
                note=note,
                path=path,
                line=line,
                column=column,
                cwd=cwd,
                filetype=filetype,
                git_root=git_root,
                git_repo=git_repo,
                git_branch=git_branch,
                git_commit=git_commit,
                tags=tags,
                metadata=metadata,
                clear_fields=clear_fields or (),
            )
        )

    def lifecycle_result(
        operation: Callable[..., BaseModel], identifier: str, revision: int
    ) -> CallToolResult:
        return _tool_result(
            lambda: operation(service, identifier=identifier, revision=revision)
        )

    @server.tool(
        name="friction_mark_done",
        description="Move an open item to done using its required current revision.",
    )
    def friction_mark_done(identifier: str, revision: int) -> CallToolResult:
        return lifecycle_result(operations.mark_done, identifier, revision)

    @server.tool(
        name="friction_dismiss",
        description=(
            "Move an open item to dismissed using its required current revision."
        ),
    )
    def friction_dismiss(identifier: str, revision: int) -> CallToolResult:
        return lifecycle_result(operations.dismiss, identifier, revision)

    @server.tool(
        name="friction_reopen",
        description="Move a done or dismissed item to open using its current revision.",
    )
    def friction_reopen(identifier: str, revision: int) -> CallToolResult:
        return lifecycle_result(operations.reopen, identifier, revision)

    @server.tool(
        name="friction_archive",
        description="Reversibly archive one item using its required current revision.",
    )
    def friction_archive(identifier: str, revision: int) -> CallToolResult:
        return lifecycle_result(operations.archive, identifier, revision)

    @server.tool(
        name="friction_unarchive",
        description="Restore one archived item using its required current revision.",
    )
    def friction_unarchive(identifier: str, revision: int) -> CallToolResult:
        return lifecycle_result(operations.unarchive, identifier, revision)

    @server.tool(
        name="friction_history",
        description="Return complete chronological event history without mutation.",
    )
    def friction_history(identifier: str) -> CallToolResult:
        return _tool_result(lambda: operations.history(service, identifier=identifier))

    @server.resource(
        "friction://items/{identifier}",
        name="friction_item",
        description="Canonical item and complete event history.",
        mime_type="application/json",
    )
    def friction_item_resource(identifier: str) -> str:
        return _resource_result(
            lambda: operations.get_item(
                service, identifier=identifier, include_history=True
            )
        )

    @server.resource(
        "friction://views/open",
        name="friction_open_items",
        description="First 100 active open items.",
        mime_type="application/json",
    )
    def friction_open_resource() -> str:
        return _resource_result(
            lambda: operations.list_items(
                service, statuses=(ItemStatus.OPEN,), limit=100
            )
        )

    @server.resource(
        "friction://views/recent",
        name="friction_recent_items",
        description="First 50 active items across statuses.",
        mime_type="application/json",
    )
    def friction_recent_resource() -> str:
        return _resource_result(lambda: operations.list_items(service, limit=50))

    @server.resource(
        "friction://schema",
        name="friction_schema",
        description="Canonical schemas, lifecycle, filters, and exact tool surface.",
        mime_type="application/json",
    )
    def friction_schema_resource() -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "schemas": {
                    "ItemData": ItemData.model_json_schema(),
                    "EventData": EventData.model_json_schema(),
                    "ApiError": ApiError.model_json_schema(),
                },
                "tools": list(TOOL_NAMES),
                "lifecycle": {
                    "open": ["done", "dismissed"],
                    "done": ["open"],
                    "dismissed": ["open"],
                },
                "archive_visibility": ["active", "archived", "all"],
                "mutation_revisions_required": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @server.prompt(
        name="triage_friction",
        description="Analyze active open friction without mutating it.",
    )
    def triage_friction(
        repo: str | None = None, tag: str | None = None, limit: int = 50
    ) -> str:
        if not 1 <= limit <= 100:
            raise ValueError("validation_error: limit must be between 1 and 100")
        page = operations.list_items(
            service,
            statuses=(ItemStatus.OPEN,),
            repo=repo,
            tags=(tag,) if tag else (),
            limit=limit,
        )
        payload = [item.model_dump(mode="json") for item in page.items]
        empty = "There are no matching open friction items.\n\n" if not payload else ""
        return (
            empty
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n\nReview these open friction items. Group related symptoms, identify "
            "likely root causes, call out repeated repositories or tags, and propose "
            "a prioritized action list. Do not change item status unless the user "
            "explicitly asks you to use a mutation tool."
        )

    return server
