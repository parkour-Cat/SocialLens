"""YouTube adapter. Navigate strategy; first screens come from ytInitialData. Notes: docs/platforms/youtube.md"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...models.errors import ErrorCode, SocialLensError
from ..base import Capability, PlatformAdapter, RateLimit
from ..bilibili.cursor import decode_cursor
from . import parsers

SITE = "https://www.youtube.com"


class YoutubeAdapter(PlatformAdapter):
    id = "youtube"
    name = "YouTube"
    home_url = f"{SITE}/"
    login_url = f"{SITE}/"
    login_hint = "打开 youtube.com，用 Google 账号登录（不登录也能看公开内容）"
    domains = ("www.youtube.com", "m.youtube.com")
    risk_level = "low"
    rate_limit = RateLimit(interval_s=2.0, jitter_s=1.0, page_loads=40)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a YouTube tab", 30000),
        "search_posts": Capability("search_posts", "navigate", "Search videos", 60000),
        "search_users": Capability("search_users", "navigate", "Search channels", 60000),
        "get_post": Capability("get_post", "navigate", "Video detail by video id", 60000),
        "get_comments": Capability("get_comments", "navigate", "Comments of a video", 60000),
        "get_user": Capability("get_user", "navigate", "Channel by @handle or channel id", 60000),
        "get_user_posts": Capability("get_user_posts", "navigate", "Videos of a channel", 60000),
        "get_feed": Capability("get_feed", "navigate", "Home recommendations", 60000),
        "get_replies": Capability("get_replies", "navigate", "Replies under one comment via its replies continuation", 90000),
        "get_trending": Capability("get_trending", "navigate", "Trending videos (/feed/trending)", 60000),
        "get_streams": Capability("get_streams", "navigate", "streamingData of a video (progressive mp4 urls) for download", 60000),
    }

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        p = dict(params)
        if action not in self.capabilities or action == "echo":
            return p
        cursor = decode_cursor(p.pop("cursor")) if p.get("cursor") else {}
        passthrough = {k: v for k, v in p.items() if k.startswith("_") or k == "allow_anonymous"}
        if cursor.get("tab"):
            # comments / replies page through innertube continuation tokens instead of scrolling
            extra = {"token": cursor["token"]} if cursor.get("token") else {"more": True}
            if action == "get_replies":
                extra["comment_id"] = p.get("comment_id")
            return {**passthrough, "_strategy": "call", "_tab": cursor["tab"], **extra}
        url, page_params = self._entry_url(action, p)
        return {**passthrough, "_strategy": "navigate", "url": url, "page_action": action, "page_params": page_params, "keep_tab": action not in ("get_post", "get_user", "get_streams")}

    @staticmethod
    def _entry_url(action: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kw = quote(str(p.get("keyword", "")))
        if action == "search_posts":
            return f"{SITE}/results?search_query={kw}&sp=EgIQAQ%253D%253D", {"keyword": p.get("keyword")}
        if action == "search_users":
            return f"{SITE}/results?search_query={kw}&sp=EgIQAg%253D%253D", {"keyword": p.get("keyword")}
        if action in ("get_post", "get_comments", "get_streams"):
            vid = str(p.get("id") or p.get("post_id") or "")
            return f"{SITE}/watch?v={vid}", {"id": vid}
        if action == "get_replies":
            vid = str(p.get("post_id") or "")
            return f"{SITE}/watch?v={vid}", {"id": vid, "comment_id": p.get("comment_id"), "token": p.get("token")}
        if action == "get_trending":
            return f"{SITE}/feed/trending", {}
        if action in ("get_user", "get_user_posts"):
            uid = str(p.get("id") or "")
            base = f"{SITE}/{uid}" if uid.startswith("@") else (f"{SITE}/channel/{uid}" if uid.startswith("UC") else f"{SITE}/@{uid}")
            return (base + ("/videos" if action == "get_user_posts" else "")), {"id": uid}
        return f"{SITE}/", {}

    def parse(self, action: str, raw: Any) -> Any:
        fn = getattr(parsers, f"parse_{action}", None)
        return fn(raw) if fn else raw

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """yt-dlp (best quality, merged with ffmpeg). The watch page's own progressive urls are kept
        behind mode=progressive for experiments: as of 2026-09 they answer 403 without a PO token."""
        from ...download import ytdlp_path

        url = post.get("url") or f"{SITE}/watch?v={post.get('id')}"
        if params.get("mode") != "progressive":
            if not ytdlp_path():
                raise SocialLensError(
                    ErrorCode.UNSUPPORTED,
                    "YouTube download needs yt-dlp: the watch page's stream urls are PO-token protected and answer 403 even from the page. "
                    "Install it into the backend env with `uv sync --extra download` (or put yt-dlp on PATH).",
                )
            return [{"index": 0, "type": "video", "url": url, "tool": "yt-dlp", "ext": "mp4"}]
        streams = await run("get_streams", {"id": post["id"]})  # mode=progressive: plain-url formats, usually 403 (2026-09)
        return parsers.pick_stream_source(streams)

