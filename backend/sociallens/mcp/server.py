"""MCP server: a thin stdio shell over the local REST API.

No business logic lives here. Every tool is one HTTP call to the backend (default
http://127.0.0.1:17800, override with SOCIALLENS_URL); the backend does routing, parsing and
caching. Run with `uv run sociallens-mcp` or `python -m sociallens.mcp`.

Uses the official MCP Python SDK 2.x (`mcp.server.mcpserver.MCPServer`).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

DEFAULT_URL = "http://127.0.0.1:17800"
TIMEOUT_S = 240.0  # page-level tasks can take a while (navigate + scroll); the backend has its own per-task timeout

INSTRUCTIONS = """SocialLens exposes the user's own logged-in social media accounts (running in their Chrome
extension) as data tools. Platform ids: bilibili, xiaohongshu, douyin, kuaishou, weixin_mp (公众号),
x, youtube, weixin_channels (视频号, backend-only, no public browsing). Call `list_platforms` first to see which
are logged in; if a platform is not logged in, tell the user the login_url / login_hint from that result
and stop. Never try to work around captchas, risk control or login walls: a `captcha_required`
error means the user must handle it in the browser, then call `resume`.

Lists return {items, cursor, total}: pass `cursor` back to get the next page. Cursors are short-lived
(they pin a browser tab); a `cursor_expired` error means start again from page 1. 小红书 ids need the
`xsec_token` that came with the item that referenced them. Each call drives a real browser tab, so
requests are rate limited per platform; expect a few seconds each."""


class Backend:
    """HTTP client for the REST API; one instance per server."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def call(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict | None = None) -> dict[str, Any]:
        query = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=TIMEOUT_S) as client:
                res = await client.request(method, path, params=query, json=body)
        except httpx.ConnectError as e:
            raise ToolError(f"SocialLens backend is not running at {self.base_url} (start it with `uv run sociallens`): {e}") from e
        except httpx.TimeoutException as e:
            raise ToolError(f"backend did not answer within {TIMEOUT_S:.0f}s: {e}") from e
        try:
            payload = res.json()
        except ValueError as e:
            raise ToolError(f"backend returned non-JSON (HTTP {res.status_code}): {res.text[:200]}") from e
        if not isinstance(payload, dict) or not payload.get("success"):
            err = (payload or {}).get("error") if isinstance(payload, dict) else None
            if isinstance(err, dict):
                msg = f"{err.get('code')}: {err.get('message')}"
                details = err.get("details")
                if details:
                    msg += f" {json.dumps(details, ensure_ascii=False)[:500]}"
                raise ToolError(msg)
            raise ToolError(f"backend error HTTP {res.status_code}: {res.text[:300]}")
        payload.pop("success", None)
        return payload


def build_server(base_url: str | None = None) -> MCPServer:
    backend = Backend(base_url or os.environ.get("SOCIALLENS_URL") or DEFAULT_URL)
    server = MCPServer("sociallens", instructions=INSTRUCTIONS, version="0.1.0")

    # ---- system --------------------------------------------------------------------

    @server.tool(description="Backend health, extension connection, and per-platform login state / open tabs.")
    async def status() -> dict[str, Any]:
        return await backend.call("GET", "/api/v1/status")

    @server.tool(description="All platforms with id, name, login_url, login_hint, logged_in and capability names. Call this first.")
    async def list_platforms() -> dict[str, Any]:
        platforms = await backend.call("GET", "/api/v1/platforms")
        state = await backend.call("GET", "/api/v1/status")
        logged = (state.get("data") or {}).get("platforms") or {}
        items = platforms.get("data") or []
        for p in items if isinstance(items, list) else []:
            if isinstance(p, dict):
                p["logged_in"] = (logged.get(p.get("id")) or {}).get("logged_in")
        return platforms

    @server.tool(description="Capabilities (actions, strategy, timeouts) of one platform.")
    async def get_capabilities(platform: str) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/capabilities")

    @server.tool(description="Resume a platform queue that paused itself after captcha_required / rate_limited, once the user has dealt with it in the browser.")
    async def resume(platform: str) -> dict[str, Any]:
        return await backend.call("POST", f"/api/v1/{platform}/resume")

    @server.tool(description="Look up a task by id (state, result, error) for long-running calls that returned a task_id.")
    async def get_task(task_id: str) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/tasks/{task_id}")

    # ---- data ----------------------------------------------------------------------

    @server.tool(description="Search a platform. type=post searches posts/videos/notes, type=user searches accounts. Returns {items, cursor, total}; pass cursor back for the next page.")
    async def search(platform: str, keyword: str, type: str = "post", cursor: str | None = None, order: str | None = None) -> dict[str, Any]:
        if type not in ("post", "user"):
            raise ToolError("type must be 'post' or 'user'")
        return await backend.call("GET", f"/api/v1/{platform}/search", {"keyword": keyword, "type": type, "cursor": cursor, "order": order})

    @server.tool(description="One post / video / note / article by its platform id (小红书 needs xsec_token from the referencing item). Includes media urls and metrics.")
    async def get_post(platform: str, post_id: str, xsec_token: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/posts/{post_id}", {"xsec_token": xsec_token})

    @server.tool(description="Comments of a post, paginated with cursor. `mode` is a platform-specific sort (bilibili: 2=time 3=hot).")
    async def get_comments(platform: str, post_id: str, cursor: str | None = None, mode: int | None = None, xsec_token: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/posts/{post_id}/comments", {"cursor": cursor, "mode": mode, "xsec_token": xsec_token})

    @server.tool(description="Replies under one comment (楼中楼), paginated with cursor. comment_id comes from get_comments items; their raw.reply_count / sub_comment_count tells whether there are any.")
    async def get_replies(platform: str, post_id: str, comment_id: str, cursor: str | None = None, xsec_token: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/posts/{post_id}/comments/{comment_id}/replies", {"cursor": cursor, "xsec_token": xsec_token})

    @server.tool(description="Profile of a user / channel / account by platform id or handle (youtube accepts @handle, x accepts screen name).")
    async def get_user(platform: str, user_id: str, xsec_token: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/users/{user_id}", {"xsec_token": xsec_token})

    @server.tool(description="Posts of a user / channel, newest first, paginated with cursor.")
    async def get_user_posts(platform: str, user_id: str, cursor: str | None = None, order: str | None = None, xsec_token: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/users/{user_id}/posts", {"cursor": cursor, "order": order, "xsec_token": xsec_token})

    @server.tool(description="The logged-in account's home / recommendation feed, paginated with cursor.")
    async def get_feed(platform: str, cursor: str | None = None) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/feed", {"cursor": cursor})

    @server.tool(description="Trending list of a platform: hot videos (bilibili, youtube: items are posts) or hot search topics (douyin, x, xiaohongshu: items have rank/title/heat/url).")
    async def get_trending(platform: str) -> dict[str, Any]:
        return await backend.call("GET", f"/api/v1/{platform}/trending")

    @server.tool(description="Collect many pages of a list action in one call: action is one of search_posts / search_users / get_comments / get_replies / get_user_posts / get_feed / get_trending, params are that action's params (keyword, post_id, user_id, comment_id, xsec_token...). Pages until `limit` items (default 100, max 1000), the end of the list, or max_pages. Result: items, count, pages, complete, stopped_by (limit|no_more|max_pages|error), error. Prefer this over looping cursors yourself.")
    async def collect(platform: str, action: str, params: dict[str, Any] | None = None, limit: int = 100, max_pages: int = 20, wait: bool = True, wait_s: float = 900) -> dict[str, Any]:
        return await backend.call("POST", f"/api/v1/{platform}/collect", body={"action": action, "params": params or {}, "limit": limit, "max_pages": max_pages, "wait": wait, "wait_s": wait_s})

    # ---- downloads -----------------------------------------------------------------

    @server.tool(description="Download a post's media (video / images) to the local disk under data/downloads/{platform}/{author}/. Returns the task with file paths; with wait=false poll get_task. media_index picks one MediaItem of the post; mode=mp4 forces single-file B 站 download.")
    async def download(platform: str, post_id: str, media_index: int | None = None, xsec_token: str | None = None, mode: str | None = None, wait: bool = True, wait_s: float = 600) -> dict[str, Any]:
        body = {k: v for k, v in {"media_index": media_index, "xsec_token": xsec_token, "mode": mode, "wait": wait, "wait_s": wait_s}.items() if v is not None}
        return await backend.call("POST", f"/api/v1/{platform}/posts/{post_id}/download", body=body)

    @server.tool(description="Recent download tasks (paths, progress, errors).")
    async def list_downloads(platform: str | None = None, limit: int = 20) -> dict[str, Any]:
        return await backend.call("GET", "/api/v1/downloads", {"platform": platform, "limit": limit})

    # ---- resources -----------------------------------------------------------------

    @server.resource("sociallens://platforms", description="Platform list with login guidance, as JSON.", mime_type="application/json")
    async def platforms_resource() -> str:
        try:
            return json.dumps(await backend.call("GET", "/api/v1/platforms"), ensure_ascii=False, indent=2)
        except ToolError as e:
            raise ResourceError(str(e)) from e

    @server.resource("sociallens://raw/{platform}/{date}", description="Raw captured responses saved for a platform on a date (YYYY-MM-DD or 'today'), for inspecting what the site returns.", mime_type="application/json")
    async def raw_resource(platform: str, date: str) -> str:
        try:
            return json.dumps(await backend.call("GET", f"/api/v1/{platform}/raw", {"date": None if date == "today" else date}), ensure_ascii=False, indent=2)
        except ToolError as e:
            raise ResourceError(str(e)) from e

    return server


def main() -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)  # stderr noise for the MCP host
    build_server().run("stdio")


if __name__ == "__main__":
    main()
