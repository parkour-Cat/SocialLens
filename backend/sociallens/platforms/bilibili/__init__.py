"""B 站 adapter. Page-side actions live in extension/src/page/platforms/bilibili.ts;
this side declares capabilities, maps REST params to action params and parses raw JSON
into unified models. Interface notes: docs/platforms/bilibili.md"""

from __future__ import annotations

from typing import Any

from ..base import Capability, PlatformAdapter, RateLimit
from . import parsers
from .cursor import decode_cursor


class BilibiliAdapter(PlatformAdapter):
    id = "bilibili"
    name = "B 站"
    home_url = "https://www.bilibili.com/"
    login_url = "https://www.bilibili.com/"
    login_hint = "打开 bilibili.com，右上角登录（扫码或账号密码）"
    domains = ("www.bilibili.com", "search.bilibili.com", "space.bilibili.com", "t.bilibili.com")
    risk_level = "low"
    rate_limit = RateLimit(interval_s=2.0, jitter_s=1.0, page_loads=40)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in B 站 tab", 30000),
        "search_posts": Capability("search_posts", "call", "Search videos by keyword (order: totalrank|click|pubdate|dm|stow)", 30000),
        "search_users": Capability("search_users", "call", "Search users by keyword", 30000),
        "get_post": Capability("get_post", "call", "Video detail by BV id or aid", 30000),
        "get_user": Capability("get_user", "call", "User profile + follower counts by mid", 30000),
        "get_comments": Capability("get_comments", "call", "Top-level comments of a video (mode: 3 hot | 2 time)", 30000),
        "get_user_posts": Capability("get_user_posts", "call", "Videos uploaded by a user, newest first", 30000),
        "get_replies": Capability("get_replies", "call", "Replies under one comment (root rpid), paged", 30000),
        "get_trending": Capability("get_trending", "call", "Popular videos (综合热门), paged", 30000),
        "get_play_url": Capability("get_play_url", "call", "Stream URLs of one page (cid) of a video: mode=dash (video+audio, needs ffmpeg) or mp4", 30000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        cursor = p.pop("cursor", None)
        if cursor:
            p.update(decode_cursor(cursor))
        return p

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """B 站 needs a playurl call per page. DASH (best quality, separate video/audio, merged with
        ffmpeg) when ffmpeg is available, else a single mp4 (up to 1080p for logged-in accounts)."""
        from ...download import ffmpeg_path

        mode = params.get("mode") or ("dash" if ffmpeg_path() else "mp4")
        headers = {"Referer": "https://www.bilibili.com/"}
        out: list[dict[str, Any]] = []
        for i, m in enumerate(post.get("media") or []):
            cid = (m.get("extra") or {}).get("cid")
            if m.get("type") != "video" or not cid:
                if m.get("url"):
                    out.append({"index": i, "type": m.get("type"), "url": m["url"], "headers": m.get("headers") or {}})
                continue
            play = await run("get_play_url", {"id": post["id"], "cid": cid, "mode": mode})
            src = parsers.pick_play_source(play, mode)
            if src:
                out.append({"index": i, "headers": headers, **src})
        return out

