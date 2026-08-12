import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent, TextResourceContents
from pydantic import AnyUrl

from friction.interfaces.mcp.server import TOOL_NAMES, create_mcp_server
from friction.storage import create_service


def test_mcp_discovery_tools_resources_prompt_and_structured_errors(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        server = create_mcp_server(create_service(tmp_path / "in-process.db"))
        async with create_connected_server_and_client_session(server) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
            prompts = await client.list_prompts()

            assert tuple(tool.name for tool in tools.tools) == TOOL_NAMES
            assert {str(resource.uri) for resource in resources.resources} == {
                "friction://views/open",
                "friction://views/recent",
                "friction://schema",
            }
            assert [
                str(template.uriTemplate) for template in templates.resourceTemplates
            ] == ["friction://items/{identifier}"]
            assert [prompt.name for prompt in prompts.prompts] == ["triage_friction"]

            added = await client.call_tool(
                "friction_add",
                {
                    "note": "MCP integration capture",
                    "path": "/tmp/mcp-source.py",
                    "tags": ["agent"],
                    "metadata": {"suite": "integration"},
                },
            )
            assert not added.isError
            assert added.structuredContent is not None
            assert added.structuredContent["source"] == "mcp"
            identifier = added.structuredContent["id"]

            empty_update = await client.call_tool(
                "friction_update", {"identifier": identifier, "revision": 1}
            )
            assert empty_update.isError
            assert empty_update.structuredContent is not None
            assert empty_update.structuredContent["code"] == "validation_error"

            cleared = await client.call_tool(
                "friction_update",
                {
                    "identifier": identifier,
                    "revision": 1,
                    "clear_fields": ["path"],
                },
            )
            assert not cleared.isError
            assert cleared.structuredContent is not None
            assert cleared.structuredContent["path"] is None

            detail = await client.call_tool(
                "friction_get", {"identifier": identifier, "include_history": True}
            )
            assert detail.structuredContent is not None
            assert len(detail.structuredContent["events"]) == 2

            stale = await client.call_tool(
                "friction_mark_done", {"identifier": identifier, "revision": 99}
            )
            assert stale.isError
            assert stale.structuredContent is not None
            assert stale.structuredContent["code"] == "revision_conflict"
            assert stale.structuredContent["details"]["actual_revision"] == 2

            listed = await client.call_tool(
                "friction_list", {"sources": ["mcp"], "limit": 1, "offset": 0}
            )
            searched = await client.call_tool(
                "friction_search", {"query": "integration", "tags": ["agent"]}
            )
            assert listed.structuredContent is not None
            assert listed.structuredContent["count"] == 1
            assert searched.structuredContent is not None
            assert searched.structuredContent["count"] == 1

            revision = 2
            for tool_name, expected_status in (
                ("friction_mark_done", "done"),
                ("friction_reopen", "open"),
                ("friction_dismiss", "dismissed"),
            ):
                changed = await client.call_tool(
                    tool_name, {"identifier": identifier, "revision": revision}
                )
                assert not changed.isError
                assert changed.structuredContent is not None
                assert changed.structuredContent["status"] == expected_status
                revision = changed.structuredContent["revision"]

            archived = await client.call_tool(
                "friction_archive", {"identifier": identifier, "revision": revision}
            )
            assert archived.structuredContent is not None
            assert archived.structuredContent["archived_at"] is not None
            restored = await client.call_tool(
                "friction_unarchive",
                {
                    "identifier": identifier,
                    "revision": archived.structuredContent["revision"],
                },
            )
            assert restored.structuredContent is not None
            assert restored.structuredContent["archived_at"] is None
            history = await client.call_tool(
                "friction_history", {"identifier": identifier}
            )
            assert history.structuredContent is not None
            assert len(history.structuredContent["events"]) == 7

            schema = await client.read_resource(AnyUrl("friction://schema"))
            schema_content = schema.contents[0]
            assert isinstance(schema_content, TextResourceContents)
            assert schema_content.mimeType == "application/json"
            assert "mutation_revisions_required" in schema_content.text

            item_resource = await client.read_resource(
                AnyUrl(f"friction://items/{identifier}")
            )
            item_content = item_resource.contents[0]
            assert isinstance(item_content, TextResourceContents)
            assert identifier in item_content.text

            for uri in ("friction://views/open", "friction://views/recent"):
                view = await client.read_resource(AnyUrl(uri))
                view_content = view.contents[0]
                assert isinstance(view_content, TextResourceContents)
                assert '"count"' in view_content.text

            prompt = await client.get_prompt(
                "triage_friction", {"tag": "agent", "limit": "10"}
            )
            prompt_content = prompt.messages[0].content
            assert isinstance(prompt_content, TextContent)
            assert "Do not change item status" in prompt_content.text

    anyio.run(scenario)


def test_real_stdio_mcp_subprocess_smoke(tmp_path: Path) -> None:
    async def scenario() -> None:
        executable = Path(sys.executable).with_name("friction")
        database = tmp_path / "stdio.db"
        parameters = StdioServerParameters(
            command=str(executable),
            args=["--db", str(database), "mcp"],
            cwd=Path.cwd(),
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as client,
        ):
            await client.initialize()
            tools = await client.list_tools()
            assert tuple(tool.name for tool in tools.tools) == TOOL_NAMES
            added = await client.call_tool(
                "friction_add", {"note": "stdio subprocess capture"}
            )
            assert not added.isError
            assert added.structuredContent is not None
            loaded = await client.call_tool(
                "friction_get",
                {"identifier": added.structuredContent["id"]},
            )
            assert not loaded.isError
            assert loaded.structuredContent is not None
            assert loaded.structuredContent["item"]["note"] == (
                "stdio subprocess capture"
            )

    anyio.run(scenario)
