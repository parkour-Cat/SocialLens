"""抖音 adapter. Navigate strategy like 小红书: the site issues its own signed requests.
Interface notes: docs/platforms/douyin.md; page actions: extension/src/page/platforms/douyin.ts."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.douyin.com"


class DouyinAdapter(PlatformAdapter):
    id = "douyin"
    name = "抖音"
    home_url = f"{SITE}/?recommend=1"
    login_url = f"{SITE}/"
    login_hint = "打开 douyin.com，右上角登录，用抖音 App 扫码"
    domains = ("www.douyin.com",)
    risk_level = "high"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in 抖音 tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search videos by keyword (site's own search page)", 60000),
        "search_users": Capability("search_users", "navigate", "Search users by keyword", 60000),
        "get_post": Capability("get_post", "navigate", "Video detail by aweme_id", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a video", 60000),
        "get_user": Capability("get_user", "navigate", "User profile by sec_uid", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Videos posted by a user (sec_uid)", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment (expands it on the video page)", 90000),
        "get_trending": Capability("get_trending", "navigate", "Hot search list (/hot)", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home recommendations", 60000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}
        if cursor.get("tab"):
            return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], "more": True, **{k: v for k, v in cursor.items() if k != "tab"}, **({"comment_id": p.get("comment_id")} if action == "get_replies" else {})}
        url, page_params = self._entry_url(action, p)
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if action == "search_posts":
            return f"{SITE}/search/{quote(str(p.get('keyword', '')))}?type=video", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/search/{quote(str(p.get('keyword', '')))}?type=user", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments"):
            vid = str(p.get("id") or p.get("post_id") or "")
            return f"{SITE}/video/{vid}", {"id": vid}
        if action == "get_replies":
            vid = str(p.get("post_id") or "")
            return f"{SITE}/video/{vid}", {"id": vid, "comment_id": p.get("comment_id")}
        if action == "get_trending":
            return f"{SITE}/hot", {}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "")
            return f"{SITE}/user/{uid}", {"id": uid}
        return f"{SITE}/?recommend=1", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
