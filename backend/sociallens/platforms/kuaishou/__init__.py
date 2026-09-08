"""快手 adapter. Navigate strategy: the site issues its own GraphQL requests, captures are
matched by operationName. Interface notes: docs/platforms/kuaishou.md"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.kuaishou.com"


class KuaishouAdapter(PlatformAdapter):
    id = "kuaishou"
    name = "快手"
    home_url = f"{SITE}/?isHome=1"
    login_url = f"{SITE}/"
    login_hint = "打开 kuaishou.com，右上角登录，用快手 App 扫码"
    domains = ("www.kuaishou.com",)
    risk_level = "medium"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=20)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in 快手 tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search videos by keyword", 60000),
        "search_users": Capability("search_users", "navigate", "Search users by keyword", 60000),
        "get_post": Capability("get_post", "navigate", "Video detail by photoId", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a video", 60000),
        "get_user": Capability("get_user", "navigate", "User profile by userId", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Videos of a user", 60000),
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
        kw = quote(str(p.get("keyword", "")))
        if action == "search_posts":
            return f"{SITE}/search/video?searchKey={kw}", {"keyword": p.get("keyword")}
        if action == "search_users":
            # There is no separate user-search route (`/search/author` is read as the keyword
            # "author"); the video search page also requests /rest/v/search/user for the keyword.
            return f"{SITE}/search/video?searchKey={kw}", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments"):
            vid = str(p.get("id") or p.get("post_id") or "")
            return f"{SITE}/short-video/{vid}", {"id": vid}
        if action == "get_replies":
            vid = str(p.get("post_id") or "")
            return f"{SITE}/short-video/{vid}", {"id": vid, "comment_id": p.get("comment_id")}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "")
            return f"{SITE}/profile/{uid}", {"id": uid}
        return f"{SITE}/?isHome=1", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
