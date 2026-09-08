"""小红书 adapter.

Every action runs in a tab opened on the right page (navigate strategy) and lets the site
issue its own signed requests. Pagination continues in that tab by scrolling: the cursor
carries the tab id (`_tab`) plus whatever the page needs. Interface notes:
docs/platforms/xiaohongshu.md; page actions: extension/src/page/platforms/xiaohongshu.ts.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.xiaohongshu.com"


class XiaohongshuAdapter(PlatformAdapter):
    id = "xiaohongshu"
    name = "小红书"
    home_url = f"{SITE}/explore"
    login_url = f"{SITE}/explore"
    login_hint = "打开 xiaohongshu.com，用小红书 App 扫码登录"
    domains = ("www.xiaohongshu.com", "edith.xiaohongshu.com")
    risk_level = "high"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in 小红书 tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search notes by keyword (site's own search page)", 60000),
        "search_users": Capability("search_users", "navigate", "Search users by keyword", 60000),
        "get_post": Capability("get_post", "navigate", "Note detail; needs xsec_token from a list/search result", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a note; needs xsec_token", 60000),
        "get_user": Capability("get_user", "navigate", "User profile", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Notes posted by a user", 60000),
        "get_replies": Capability("get_replies", "navigate", "Sub-comments under one comment (expands it on the note page)", 90000),
        "get_trending": Capability("get_trending", "navigate", "Search-box suggestions (猜你想搜, personalised; the site has no public hot list)", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home recommendations", 60000),
    }

    # ---- REST params -> task params -------------------------------------------

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p  # generic page actions (navigate, read_global, ...) take their params verbatim
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}

        if cursor.get("tab"):
            # Continue scrolling in the tab the first call left open.
            return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], "more": True, **{k: v for k, v in cursor.items() if k != "tab"}, **({"comment_id": p.get("comment_id")} if action == "get_replies" else {})}

        url, page_params = self._entry_url(action, p)
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action != "get_post" and action != "get_user"}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if action in ("search_posts", "search_users"):
            kw = quote(str(p.get("keyword", "")))
            kind = "&type=user" if action == "search_users" else ""
            return f"{SITE}/search_result?keyword={kw}&source=web_explore_feed{kind}", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments"):
            note_id = str(p.get("id") or p.get("post_id") or "")
            token = p.get("xsec_token")
            q = f"?xsec_token={quote(str(token))}&xsec_source=pc_search" if token else ""
            return f"{SITE}/explore/{note_id}{q}", {"id": note_id}
        if action == "get_replies":
            note_id = str(p.get("post_id") or "")
            token = p.get("xsec_token")
            q = f"?xsec_token={quote(str(token))}&xsec_source=pc_search" if token else ""
            return f"{SITE}/explore/{note_id}{q}", {"id": note_id, "comment_id": p.get("comment_id")}
        if action == "get_trending":
            return f"{SITE}/explore", {}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "")
            token = p.get("xsec_token")
            q = f"?xsec_token={quote(str(token))}&xsec_source=pc_note" if token else ""
            return f"{SITE}/user/profile/{uid}{q}", {"id": uid}
        if action == "get_feed":
            return f"{SITE}/explore", {}
        return f"{SITE}/explore", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
