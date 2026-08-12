"""Public local stdio MCP adapter entry point."""

from pathlib import Path

from friction.interfaces.mcp.server import create_mcp_server
from friction.storage import create_service, resolve_database_path

__all__ = ["create_mcp_server", "run_mcp"]


def run_mcp(database_path: str | Path | None = None) -> None:
    """Apply migrations and run the Friction MCP server over stdio only."""
    resolved = resolve_database_path(database_path)
    service = create_service(resolved)
    create_mcp_server(service).run(transport="stdio")
