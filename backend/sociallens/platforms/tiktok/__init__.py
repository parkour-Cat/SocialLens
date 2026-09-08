"""TikTok adapter. Navigate strategy (signed like 抖音). Notes: docs/platforms/tiktok.md"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models.errors import ErrorCode, SocialLensError
from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.tiktok.com"


class TiktokAdapter(PlatformAdapter):
    id = "tiktok"
    name = "TikTok"
    home_url = f"{SITE}/foryou"
    login_url = f"{SITE}/login"
    login_hint = "打开 tiktok.com 登录（需要能访问 TikTok 的网络；不登录也能看部分公开内容）"
    domains = ("www.tiktok.com", "tiktok.com")
    risk_level = "high"
    rate_limit = RateLimit(interval_s=4.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a TikTok tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search videos", 60000),
        "search_users": Capability("search_users", "navigate", "Search users", 60000),
        "get_post": Capability("get_post", "navigate", "Video by id (@user/video/{id} or bare id)", 90000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a video (the page opens the comment panel)", 90000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment (expands it in the comment panel)", 90000),
        "get_user": Capability("get_user", "navigate", "User by @uniqueId", 90000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Videos of a user", 60000),
        "get_feed": Capability("get_feed", "navigate", "For You feed", 60000),
        "get_trending": Capability("get_trending", "navigate", "Explore (trending) videos", 60000),
    }

    _authors: dict[str, str] = {}

    async def prepare(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """A bare video id has no page of its own (the @user path is required and the @tiktok
        placeholder does not redirect): ask the public oembed endpoint for the author handle."""
        if action not in ("get_post", "get_comments", "get_replies") or params.get("cursor"):
            return params
        vid = str(params.get("id") or params.get("post_id") or "")
        if "/" in vid or "@" in vid or not vid.isdigit() or params.get("author"):
            return params
        if vid not in self._authors:
            import httpx

            from ...download import resolve_proxy

            try:
                async with httpx.AsyncClient(timeout=15, proxy=resolve_proxy("system")) as client:
                    r = await client.get("https://www.tiktok.com/oembed", params={"url": f"{SITE}/@x/video/{vid}"})
                    author = (r.json() or {}).get("author_unique_id") if r.status_code == 200 else None
            except Exception:  # noqa: BLE001
                author = None
            if not author:
                raise SocialLensError(ErrorCode.NOT_FOUND, f"cannot resolve the author of video {vid} (oembed); pass id as @user/video/{vid}")
            self._authors[vid] = str(author)
        return {**params, "author": self._authors[vid]}

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
        # cold TikTok tabs are slow; keep every navigate tab so warm tabs get reused (GC still reclaims them).
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": True}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kw = quote(str(p.get("keyword", "")))
        vid = str(p.get("id") or p.get("post_id") or "")
        if action == "search_posts":
            return f"{SITE}/search/video?q={kw}", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/search/user?q={kw}", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments", "get_replies"):
            if vid.startswith("http"):
                return vid, {"id": vid.rstrip("/").split("/")[-1], "post_id": vid.rstrip("/").split("/")[-1], "comment_id": p.get("comment_id")}
            if "/video/" in vid:  # "@user/video/123"
                return f"{SITE}/{vid.lstrip('/')}", {"id": vid.split("/")[-1], "post_id": vid.split("/")[-1], "comment_id": p.get("comment_id")}
            author = str(p.get("author") or "").lstrip("@")
            return f"{SITE}/@{author}/video/{vid}", {"id": vid, "post_id": vid, "comment_id": p.get("comment_id")}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "").lstrip("@")
            return f"{SITE}/@{uid}", {"id": uid}
        if action == "get_trending":
            return f"{SITE}/explore", {}
        return f"{SITE}/foryou", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Video urls are bound to the browser's cookies, so the backend cannot fetch them: yt-dlp does."""
        from ...download import ytdlp_path

        if not ytdlp_path():
            raise SocialLensError(ErrorCode.UNSUPPORTED, "TikTok download needs yt-dlp (`uv sync --extra download`): video urls are cookie-bound and answer 403 from outside the browser.")
        return [{"index": 0, "type": "video", "url": post.get("url") or f"{SITE}/@tiktok/video/{post.get('id')}", "tool": "yt-dlp", "ext": "mp4"}]
