"""MCP shell: a real backend on a free port, the MCP server as a stdio subprocess, talked to with
the SDK client. No extension is connected, so data tools must surface `extension_offline` as tool
errors while system tools work."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sociallens.config import Settings
from sociallens.main import create_app

EXPECTED_TOOLS = {
    "status",
    "list_platforms",
    "get_capabilities",
    "resume",
    "get_task",
    "search",
    "get_post",
    "get_comments",
    "get_user",
    "get_user_posts",
    "get_feed",
    "get_trending",
    "get_replies",
    "download",
    "collect",
    "list_downloads",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def backend_url(tmp_path):
    port = _free_port()
    app = create_app(Settings(data_dir=tmp_path / "data", port=port, log_level="WARNING"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(url + "/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("backend did not start")
    yield url
    server.should_exit = True
    thread.join(10)


def _params(backend_url: str) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "sociallens.mcp"], env={**os.environ, "SOCIALLENS_URL": backend_url})


def _payload(result) -> dict:
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_tools_and_system_calls(backend_url):
    async with stdio_client(_params(backend_url)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "sociallens"
            assert "SocialLens" in (init.instructions or "")

            tools = {t.name for t in (await session.list_tools()).tools}
            assert EXPECTED_TOOLS <= tools

            st = _payload(await session.call_tool("status", {}))
            assert st["data"]["extension"]["online"] is False

            platforms = _payload(await session.call_tool("list_platforms", {}))
            ids = {p["id"]: p for p in platforms["data"]}
            assert {"bilibili", "xiaohongshu", "douyin", "youtube", "x"} <= set(ids)
            assert ids["youtube"]["login_url"] and not ids["youtube"]["logged_in"]  # None: no extension connected

            caps = _payload(await session.call_tool("get_capabilities", {"platform": "bilibili"}))
            assert "search_posts" in json.dumps(caps)


async def test_data_tool_errors_without_extension(backend_url):
    async with stdio_client(_params(backend_url)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("search", {"platform": "bilibili", "keyword": "露营"})
            assert res.is_error
            assert "extension_offline" in res.content[0].text

            res = await session.call_tool("get_post", {"platform": "nope", "post_id": "1"})
            assert res.is_error and "unknown_platform" in res.content[0].text

            res = await session.call_tool("search", {"platform": "bilibili", "keyword": "x", "type": "video"})
            assert res.is_error and "type must be" in res.content[0].text


async def test_resources(backend_url):
    async with stdio_client(_params(backend_url)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            uris = {str(r.uri) for r in (await session.list_resources()).resources}
            assert "sociallens://platforms" in uris
            body = json.loads((await session.read_resource("sociallens://platforms")).contents[0].text)
            assert any(p["id"] == "kuaishou" for p in body["data"])
            raw = json.loads((await session.read_resource("sociallens://raw/bilibili/today")).contents[0].text)
            assert raw["data"] == []
