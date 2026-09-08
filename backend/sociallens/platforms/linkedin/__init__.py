"""LinkedIn adapter. Notes: docs/platforms/linkedin.md

Two kinds of pages coexist on linkedin.com (2026-09):
- the new server-driven UI (feed, search, profile top): no entity data in its RSC streams, so the
  classic voyager REST API is called from inside a LinkedIn tab (call strategy) for feed, post
  detail, profile and people search;
- the classic Ember app on /in/{vanity}/recent-activity/all/ and /feed/update/{urn}/, which issues
  dash GraphQL calls the page script captures (navigate strategy) for member posts, comments and replies.
"""

from __future__ import annotations

import re
from typing import Any

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.linkedin.com"
NAVIGATE_ACTIONS = ("get_user_posts", "get_comments", "get_replies")


def _activity_id(v: Any) -> str:
    s = str(v or "")
    m = re.search(r"(?:activity|ugcPost|share)[:%3A]+(\d+)", s) or re.search(r"(\d{15,})", s)
    return m.group(1) if m else s


def _vanity(v: Any) -> str:
    s = str(v or "")
    m = re.search(r"/in/([^/?#]+)", s)
    return m.group(1) if m else s.strip("/").lstrip("@")


class LinkedinAdapter(PlatformAdapter):
    id = "linkedin"
    name = "LinkedIn"
    home_url = f"{SITE}/feed/"
    login_url = f"{SITE}/login"
    login_hint = "打开 linkedin.com 登录"
    domains = ("www.linkedin.com", "linkedin.com")
    risk_level = "high"
    rate_limit = RateLimit(interval_s=6.0, jitter_s=3.0, page_loads=8)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a LinkedIn tab", 30000),
        "search_users": Capability("search_users", "call", "People search (dash search clusters; typeahead fallback)", 45000),
        "get_post": Capability("get_post", "call", "Post by activity id (urn:li:activity:{id}) with its highlighted comments", 45000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a post (the classic post page; 加载更多评论 pages)", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment (expanded on the classic post page)", 60000),
        "get_user": Capability("get_user", "call", "Profile by vanity name (/in/{vanity})", 45000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Posts of a member (/in/{vanity}/recent-activity/all/)", 60000),
        "get_feed": Capability("get_feed", "call", "Home feed (chronological)", 45000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        if action in NAVIGATE_ACTIONS:
            passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}
            if cursor.get("tab"):
                extra = {k: v for k, v in cursor.items() if k != "tab"}
                ids = {k: p.get(k) for k in ("post_id", "comment_id", "id") if p.get(k)}
                return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], "more": True, **extra, **ids}
            if action == "get_user_posts":
                vanity = _vanity(p.get("id"))
                return {**passthrough, "_strategy": "navigate", "url": f"{SITE}/in/{vanity}/recent-activity/all/", "page_action": action, "page_params": {"id": vanity}, "keep_tab": True}
            aid = _activity_id(p.get("id") or p.get("post_id"))
            return {**passthrough, "_strategy": "navigate", "url": f"{SITE}/feed/update/urn:li:activity:{aid}/", "page_action": action, "page_params": {"id": aid, "post_id": aid, "comment_id": p.get("comment_id")}, "keep_tab": True}
        if action == "get_post":
            p["id"] = _activity_id(p.get("id") or p.get("post_id"))
        if action == "get_user":
            p["id"] = _vanity(p.get("id"))
        return {**p, **cursor}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    def parse_with_params(self, action: str, raw: Any, params: dict[str, Any]) -> Any:
        """Carry the ids the request was about into the parser (profile vanity, post id, parent comment)."""
        pp = params.get("page_params") if isinstance(params.get("page_params"), dict) else {}
        if action == "get_user" and isinstance(raw, dict):
            raw = {"body": raw, "url": "", "_id": params.get("id")} if "included" in raw else {**raw, "_id": params.get("id")}
        elif action in ("get_comments", "get_replies") and isinstance(raw, dict):
            raw = {**raw, "_post_id": params.get("post_id") or pp.get("post_id") or params.get("id") or pp.get("id"), "_comment_id": raw.get("_comment_id") or params.get("comment_id") or pp.get("comment_id")}
        return self.parse(action, raw)
