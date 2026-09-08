"""公众号 adapter.

Public data comes through the user's own 公众号 backend (mp.weixin.qq.com, logged in by QR):
`searchbiz` finds any account by name, `appmsg` lists any account's published articles. Both
are plain JSON calls made in the backend tab (call strategy). Article bodies are public
pages read with the navigate strategy. Interface notes: docs/platforms/weixin_mp.md
"""

from __future__ import annotations

from typing import Any

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

PAGE = 5  # both backend endpoints page by 5


class WeixinMpAdapter(PlatformAdapter):
    id = "weixin_mp"
    name = "公众号"
    home_url = "https://mp.weixin.qq.com/"
    login_url = "https://mp.weixin.qq.com/"
    login_hint = "打开 mp.weixin.qq.com（公众号后台），用微信扫码登录你自己的公众号；公域搜索和文章列表都走这个后台"
    domains = ("mp.weixin.qq.com",)
    risk_level = "high"
    rate_limit = RateLimit(interval_s=6.0, jitter_s=3.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a logged-in 公众号后台 tab", 30000),
        "search_users": Capability("search_users", "call", "Search any 公众号 by name (backend searchbiz); id = fakeid", 30000),
        "get_user": Capability("get_user", "call", "Account card by exact name or alias (backend searchbiz)", 30000),
        "get_user_posts": Capability("get_user_posts", "call", "Published articles of any 公众号 by fakeid (backend appmsg), 5 per page", 30000),
        "get_post": Capability("get_post", "navigate", "One article by URL or /s/ id: title, author, body, images, publish time", 60000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        if action in ("search_users", "get_user_posts"):
            p["begin"] = int(cursor.get("begin", 0))
        if action == "get_post":
            ident = str(p.get("id") or p.get("url") or "")
            url = ident if ident.startswith("http") else f"https://mp.weixin.qq.com/s/{ident}"
            return {**{k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}, "_strategy": "navigate", "url": url, "page_action": "get_post", "page_params": {"id": ident}, "keep_tab": False}
        return p

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw
