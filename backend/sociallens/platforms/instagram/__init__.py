"""Instagram adapter. Navigate strategy: the site issues its own GraphQL queries; the extension only captures. Notes: docs/platforms/instagram.md"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.instagram.com"


class InstagramAdapter(PlatformAdapter):
    id = "instagram"
    name = "Instagram"
    home_url = f"{SITE}/"
    login_url = f"{SITE}/accounts/login/"
    login_hint = "打开 instagram.com 登录（需要能访问 Instagram 的网络）"
    domains = ("www.instagram.com", "instagram.com")
    risk_level = "high"
    rate_limit = RateLimit(interval_s=5.0, jitter_s=3.0, page_loads=10)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through an Instagram tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Keyword search (posts / reels grid)", 60000),
        "search_users": Capability("search_users", "navigate", "Accounts from the search panel (typed like a user; no paging)", 60000),
        "get_post": Capability("get_post", "navigate", "Post or reel by shortcode (/p/{code}/, /reel/{code}/)", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a post (server-rendered first page; later pages if the site paginates on scroll)", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment (expands it on the page)", 60000),
        "get_user": Capability("get_user", "navigate", "Profile by username", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Posts of a user", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home timeline", 60000),
        "get_trending": Capability("get_trending", "navigate", "Explore grid", 60000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}
        if cursor.get("tab"):
            extra = {k: v for k, v in cursor.items() if k != "tab"}
            return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], "more": True, **extra, **({"comment_id": p.get("comment_id")} if action == "get_replies" else {})}
        url, page_params = self._entry_url(action, p)
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if action == "search_posts":
            return f"{SITE}/explore/search/keyword/?q={quote(str(p.get('keyword', '')))}", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments", "get_replies"):
            pid = str(p.get("id") or p.get("post_id") or "")
            m = re.search(r"/(p|reel|reels|tv)/([A-Za-z0-9_-]+)", pid)
            code = m.group(2) if m else pid.strip("/").split("/")[-1]
            kind = "reel" if (m and m.group(1) in ("reel", "reels")) else "p"
            url = pid if pid.startswith("http") else f"{SITE}/{kind}/{code}/"
            return url, {"id": code, "post_id": code, "comment_id": p.get("comment_id")}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "").strip("/").lstrip("@")
            url = uid if uid.startswith("http") else f"{SITE}/{uid}/"
            return url, {"id": uid.split("/")[-1]}
        if action == "get_trending":
            return f"{SITE}/explore/", {}
        return f"{SITE}/", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    def parse_with_params(self, action: str, raw: Any, params: dict[str, Any]) -> Any:
        """Comment payloads do not name their post: carry the shortcode from the request into the parser."""
        if action in ("get_comments", "get_replies") and isinstance(raw, dict):
            pp = params.get("page_params") if isinstance(params.get("page_params"), dict) else {}
            raw = {**raw, "_post_id": params.get("post_id") or params.get("id") or pp.get("post_id") or pp.get("id")}
        return self.parse(action, raw)
