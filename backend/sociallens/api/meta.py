"""What the MCP server exposes, for the console's 接口 page (REST comes from /openapi.json)."""

from __future__ import annotations

from fastapi import APIRouter

from .deps import ok

router = APIRouter(tags=["meta"])


@router.get("/mcp/tools")
async def mcp_tools():
    """Tools, resources and resource templates of the stdio MCP server, listed in-process."""
    from ..mcp.server import build_server

    server = build_server()
    tools = await server.list_tools()
    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    return ok(
        {
            "command": "uv run sociallens-mcp",
            "claude_code": "claude mcp add sociallens -- uv run --project <repo>/backend sociallens-mcp",
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools],
            "resources": [{"uri": str(r.uri), "name": r.name, "description": r.description} for r in resources],
            "resource_templates": [{"uri_template": t.uri_template, "name": t.name, "description": t.description} for t in templates],
        }
    )
