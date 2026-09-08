"""今日头条 adapter. Navigate strategy (every list endpoint carries a site-computed _signature). Notes: docs/platforms/toutiao.md"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.toutiao.com"


class ToutiaoAdapter(PlatformAdapter):
    id = "toutiao"
    name = "今日头条"
    home_url = f"{SITE}/"
    login_url = f"{SITE}/"
    login_hint = "打开 toutiao.com，点右上角登录（不登录也能看公开内容）"
    domains = ("www.toutiao.com", "so.toutiao.com", "toutiao.com")
    risk_level = "medium"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a 头条 tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search 资讯 (articles) on so.toutiao.com", 60000),
        "get_post": Capability("get_post", "navigate", "Article by group id (/article/{id}/); a full URL also works", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of an article (later pages open the comment drawer)", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment", 60000),
        "get_user": Capability("get_user", "navigate", "Author by profile token (/c/user/token/{token}/)", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Posts of an author", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home recommendation feed", 60000),
        "get_trending": Capability("get_trending", "navigate", "热榜 (hot board)", 60000),
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
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user", "get_trending")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if action == "search_posts":
            return f"https://so.toutiao.com/search?keyword={quote(str(p.get('keyword', '')))}&pd=information&source=input", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments", "get_replies"):
            pid = str(p.get("id") or p.get("post_id") or "")
            if pid.startswith("http"):
                url = pid
            elif "/" in pid:  # "video/123", "w/123"
                url = f"{SITE}/{pid.strip('/')}/"
            else:
                url = f"{SITE}/article/{pid}/"
            m = re.search(r"/(?:article|video|w|group|item|a)/?(\d+)", url) or re.search(r"(\d{8,})", url)
            gid = m.group(1) if m else pid
            return url, {"id": gid, "post_id": gid, "comment_id": p.get("comment_id")}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "")
            url = uid if uid.startswith("http") else f"{SITE}/c/user/token/{uid.strip('/')}/"
            return url, {"id": uid}
        return f"{SITE}/", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """A video page lists every quality of the same file (best first): download only the first one."""
        sources = await super().download_sources(post, run, params)
        videos = [s for s in sources if s.get("type") == "video"]
        if videos:
            return [videos[0]]
        return sources

    def parse_with_params(self, action: str, raw: Any, params: dict[str, Any]) -> Any:
        """reply_list answers do not name the article: carry the group id from the request into the parser."""
        if action in ("get_comments", "get_replies") and isinstance(raw, dict):
            pp = params.get("page_params") if isinstance(params.get("page_params"), dict) else {}
            raw = {**raw, "_post_id": params.get("post_id") or pp.get("post_id") or params.get("id") or pp.get("id")}
        return self.parse(action, raw)
