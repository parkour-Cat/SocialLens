"""Reddit adapter. Call strategy over the classic `.json` API. Notes: docs/platforms/reddit.md"""

from __future__ import annotations

from typing import Any

from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.reddit.com"


class RedditAdapter(PlatformAdapter):
    id = "reddit"
    name = "Reddit"
    home_url = f"{SITE}/"
    login_url = f"{SITE}/login/"
    login_hint = "打开 reddit.com 登录（不登录也能看公开内容，登录后才有个人首页流）"
    domains = ("www.reddit.com", "old.reddit.com", "reddit.com")
    risk_level = "medium"
    rate_limit = RateLimit(interval_s=2.0, jitter_s=1.0, page_loads=40)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a Reddit tab", 30000),
        "search_posts": Capability("search_posts", "call", "Search posts (order: relevance | hot | top | new | comments)", 30000),
        "search_users": Capability("search_users", "call", "Search users", 30000),
        "get_post": Capability("get_post", "call", "Post by id (t3 id, with or without the t3_ prefix)", 30000),
        "get_comments": Capability("get_comments", "call", "Top-level comments of a post (mode: confidence | top | new | controversial | old | qa)", 30000),
        "get_replies": Capability("get_replies", "call", "Replies under one comment", 30000),
        "get_user": Capability("get_user", "call", "User by name", 30000),
        "get_user_posts": Capability("get_user_posts", "call", "Posts submitted by a user (order: new | hot | top)", 30000),
        "get_feed": Capability("get_feed", "call", "Home feed (/best, personalised when logged in)", 30000),
        "get_trending": Capability("get_trending", "call", "r/popular", 30000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        cursor = p.pop("cursor", None)
        if cursor:
            c = decode_cursor(cursor)  # listings: {"after": "t3_..."}; comments: {"children": [ids...]}
            if isinstance(c.get("children"), list):
                p["children"] = ",".join(c["children"][:100])
                p["_rest"] = c["children"][100:]
            else:
                p.update(c)
        return p

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    def parse_with_params(self, action: str, raw: Any, params: dict[str, Any]) -> Any:
        """morechildren pages need the ids not yet fetched (kept in the built params) for the next cursor."""
        if action == "get_comments" and isinstance(raw, dict) and isinstance(raw.get("json"), dict) and params.get("_rest") is not None:
            raw = {**raw, "_rest": params["_rest"]}
        return self.parse(action, raw)

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """v.redd.it video is DASH with separate audio (merged with ffmpeg); images and galleries are direct."""
        out: list[dict[str, Any]] = []
        for i, m in enumerate(post.get("media") or []):
            if not isinstance(m, dict) or not m.get("url"):
                continue
            extra = m.get("extra") or {}
            if m.get("type") == "video" and extra.get("audio_url"):
                base = str(extra["audio_url"]).rsplit("/", 1)[0]
                audio = [f"{base}/DASH_AUDIO_128.mp4", f"{base}/DASH_AUDIO_64.mp4", f"{base}/DASH_audio.mp4"]
                out.append({"index": i, "type": "video", "url": m["url"], "ext": "mp4", "parts": [{"url": m["url"], "ext": "mp4", "headers": {}}, {"url": audio[0], "backup_urls": audio[1:], "ext": "mp4", "headers": {}, "optional": True}]})
            else:
                out.append({"index": i, "type": m.get("type"), "url": m["url"], "headers": m.get("headers") or {}})
        return out
