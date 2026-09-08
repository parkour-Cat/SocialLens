"""知乎 adapter. Navigate strategy (x-zse-96 signed requests are made by the site). Notes: docs/platforms/zhihu.md"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.zhihu.com"


class ZhihuAdapter(PlatformAdapter):
    id = "zhihu"
    name = "知乎"
    home_url = f"{SITE}/"
    login_url = f"{SITE}/signin"
    login_hint = "打开 zhihu.com，扫码或账号登录（几乎所有内容都要求登录）"
    domains = ("www.zhihu.com", "zhuanlan.zhihu.com", "zhihu.com")
    risk_level = "high"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in 知乎 tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search content (answers, articles, questions)", 60000),
        "search_users": Capability("search_users", "navigate", "Search people", 60000),
        "get_post": Capability("get_post", "navigate", "Answer (question/{qid}/answer/{aid} or answer id), article (p/{id}) or question (question/{id})", 60000),
        "get_comments": Capability("get_comments", "navigate", "Root comments of an answer / article / question", 60000),
        "get_replies": Capability("get_replies", "navigate", "Child comments of a root comment", 60000),
        "get_user": Capability("get_user", "navigate", "User by url_token", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Answers (default) or articles (order=articles) of a user", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home recommendations", 60000),
        "get_trending": Capability("get_trending", "navigate", "热榜 (hot list)", 60000),
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
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user", "get_trending")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kw = quote(str(p.get("keyword", "")))
        pid = str(p.get("id") or p.get("post_id") or "")
        if action == "search_posts":
            # the content tab is server-rendered (no request to capture); the people tab fetches, and
            # clicking 综合 from there makes the site request page 1 of the content results
            return f"{SITE}/search?type=people&q={kw}", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/search?type=people&q={kw}", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments", "get_replies"):
            return parsers.post_url(pid), {"id": pid, "comment_id": p.get("comment_id")}
        if action == "get_user":
            return f"{SITE}/people/{p.get('id')}", {"id": p.get("id")}
        if action == "get_user_posts":
            tab = "posts" if str(p.get("order", "")) == "articles" else "answers"
            return f"{SITE}/people/{p.get('id')}/{tab}", {"id": p.get("id")}
        if action == "get_trending":
            return f"{SITE}/hot", {}
        return f"{SITE}/", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
