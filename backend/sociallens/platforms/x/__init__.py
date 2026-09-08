"""X adapter. Navigate strategy; GraphQL captures matched by operation name. Notes: docs/platforms/x.md"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://x.com"


class XAdapter(PlatformAdapter):
    id = "x"
    name = "X"
    home_url = f"{SITE}/home"
    login_url = f"{SITE}/login"
    login_hint = "打开 x.com 登录（几乎所有页面都要求登录）"
    domains = ("x.com", "twitter.com")
    risk_level = "medium"
    rate_limit = RateLimit(interval_s=3.0, jitter_s=1.5, page_loads=20)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in X tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search posts (f=live latest, f=top)", 60000),
        "search_users": Capability("search_users", "navigate", "Search users", 60000),
        "get_post": Capability("get_post", "navigate", "Post detail by id", 60000),
        "get_comments": Capability("get_comments", "navigate", "Replies of a post", 60000),
        "get_user": Capability("get_user", "navigate", "User by screen name", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Posts of a user", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies to one reply (its own TweetDetail), paged by scrolling", 60000),
        "get_trending": Capability("get_trending", "navigate", "Trending topics (explore / trending tab)", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home timeline", 60000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}
        if cursor.get("tab"):
            return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], "more": True}
        url, page_params = self._entry_url(action, p)
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kw = quote(str(p.get("keyword", "")))
        if action == "search_posts":
            f = "top" if str(p.get("order", "")) == "top" else "live"
            return f"{SITE}/search?q={kw}&src=typed_query&f={f}", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/search?q={kw}&src=typed_query&f=user", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments"):
            tid = str(p.get("id") or p.get("post_id") or "")
            return f"{SITE}/i/status/{tid}", {"id": tid}
        if action == "get_replies":
            cid = str(p.get("comment_id") or "")
            return f"{SITE}/i/status/{cid}", {"id": cid, "post_id": p.get("post_id"), "comment_id": cid}
        if action == "get_trending":
            return f"{SITE}/explore/tabs/trending", {}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "").lstrip("@")
            return f"{SITE}/{uid}", {"id": uid}
        return f"{SITE}/home", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
