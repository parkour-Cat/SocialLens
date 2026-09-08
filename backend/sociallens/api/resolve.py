"""Turn whatever the user pastes (a post / profile link, a bare id, or plain words) into
{platform, kind, id, xsec_token} so the console can jump straight to the right action.

Short links (b23.tv, v.douyin.com, xhslink.com, v.kuaishou.com) are recognised by platform only:
resolving them needs a request, which the console does by opening the page through the extension.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Query

from .deps import ok

router = APIRouter(tags=["resolve"])

SHORT_HOSTS = {"b23.tv": "bilibili", "v.douyin.com": "douyin", "xhslink.com": "xiaohongshu", "v.kuaishou.com": "kuaishou", "youtu.be": "youtube", "t.co": "x", "redd.it": "reddit", "vm.tiktok.com": "tiktok", "vt.tiktok.com": "tiktok"}


def _q(url, key: str) -> str | None:
    v = parse_qs(url.query).get(key)
    return v[0] if v else None


def resolve(text: str) -> dict:
    s = text.strip()
    out: dict = {"input": s, "platform": None, "kind": "keyword", "id": None, "xsec_token": None, "url": None}
    if not s:
        return out
    # bare ids first: BV号 / av号 are unambiguous
    m = re.fullmatch(r"(BV[0-9A-Za-z]{10})|av(\d+)", s)
    if m:
        return {**out, "platform": "bilibili", "kind": "post", "id": m.group(1) or m.group(2)}
    if not re.match(r"https?://", s) and re.match(r"[\w.-]+\.[a-z]{2,}/", s):
        s = "https://" + s
    if not re.match(r"https?://", s):
        return out
    try:
        u = urlparse(s)
    except ValueError:
        return out
    host = (u.hostname or "").lower()
    path = u.path or "/"
    out["url"] = s
    out["kind"] = None  # a link we recognise the site of but not the object: the console just opens it
    if host in SHORT_HOSTS:
        return {**out, "platform": SHORT_HOSTS[host], "kind": "short_link", "id": None} if host != "youtu.be" else {**out, "platform": "youtube", "kind": "post", "id": path.strip("/").split("/")[0] or None}

    if host.endswith("bilibili.com"):
        if m := re.search(r"/video/(BV[0-9A-Za-z]{10}|av\d+)", path):
            vid = m.group(1)
            return {**out, "platform": "bilibili", "kind": "post", "id": vid[2:] if vid.startswith("av") else vid}
        if host.startswith("space.") and (m := re.match(r"/(\d+)", path)):
            return {**out, "platform": "bilibili", "kind": "user", "id": m.group(1)}
        if host.startswith("search.") and _q(u, "keyword"):
            return {**out, "platform": "bilibili", "kind": "keyword", "id": _q(u, "keyword")}
        return {**out, "platform": "bilibili"}

    if host.endswith("xiaohongshu.com"):
        token = _q(u, "xsec_token")
        if m := re.search(r"/(?:explore|discovery/item)/([0-9a-f]{24})", path):
            return {**out, "platform": "xiaohongshu", "kind": "post", "id": m.group(1), "xsec_token": token}
        if m := re.search(r"/user/profile/([0-9a-f]{24})", path):
            return {**out, "platform": "xiaohongshu", "kind": "user", "id": m.group(1), "xsec_token": token}
        if "/search_result" in path and _q(u, "keyword"):
            return {**out, "platform": "xiaohongshu", "kind": "keyword", "id": unquote(_q(u, "keyword") or "")}
        return {**out, "platform": "xiaohongshu"}

    if host.endswith("douyin.com"):
        if m := re.search(r"/(?:video|note)/(\d+)", path):
            return {**out, "platform": "douyin", "kind": "post", "id": m.group(1)}
        if m := re.search(r"/user/([\w-]+)", path):
            return {**out, "platform": "douyin", "kind": "user", "id": m.group(1)}
        if m := re.search(r"/search/([^/?]+)", path):
            return {**out, "platform": "douyin", "kind": "keyword", "id": unquote(m.group(1))}
        if _q(u, "modal_id"):
            return {**out, "platform": "douyin", "kind": "post", "id": _q(u, "modal_id")}
        return {**out, "platform": "douyin"}

    if host.endswith("kuaishou.com"):
        if m := re.search(r"/short-video/([\w-]+)", path):
            return {**out, "platform": "kuaishou", "kind": "post", "id": m.group(1)}
        if m := re.search(r"/profile/([\w-]+)", path):
            return {**out, "platform": "kuaishou", "kind": "user", "id": m.group(1)}
        if "/search/" in path and _q(u, "searchKey"):
            return {**out, "platform": "kuaishou", "kind": "keyword", "id": _q(u, "searchKey")}
        return {**out, "platform": "kuaishou"}

    if host == "mp.weixin.qq.com":
        if m := re.match(r"/s/([\w-]+)", path):
            return {**out, "platform": "weixin_mp", "kind": "post", "id": m.group(1)}
        if path.startswith("/s") and _q(u, "__biz"):
            return {**out, "platform": "weixin_mp", "kind": "post", "id": s}
        return {**out, "platform": "weixin_mp"}

    if host.endswith("channels.weixin.qq.com"):
        return {**out, "platform": "weixin_channels"}

    if host.endswith("youtube.com"):
        if path == "/watch" and _q(u, "v"):
            return {**out, "platform": "youtube", "kind": "post", "id": _q(u, "v")}
        if m := re.match(r"/(?:shorts|live|embed)/([\w-]{11})", path):
            return {**out, "platform": "youtube", "kind": "post", "id": m.group(1)}
        if m := re.match(r"/(@[\w.-]+|channel/UC[\w-]+)", path):
            return {**out, "platform": "youtube", "kind": "user", "id": m.group(1).removeprefix("channel/")}
        if path == "/results" and _q(u, "search_query"):
            return {**out, "platform": "youtube", "kind": "keyword", "id": _q(u, "search_query")}
        return {**out, "platform": "youtube"}

    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        if m := re.match(r"/(?:i/(?:web/)?status|[\w]+/status)/(\d+)", path):
            return {**out, "platform": "x", "kind": "post", "id": m.group(1)}
        if path == "/search" and _q(u, "q"):
            return {**out, "platform": "x", "kind": "keyword", "id": _q(u, "q")}
        if (m := re.match(r"/([A-Za-z0-9_]{1,15})/?$", path)) and m.group(1).lower() not in ("home", "explore", "search", "i", "settings", "messages", "notifications"):
            return {**out, "platform": "x", "kind": "user", "id": m.group(1)}
        return {**out, "platform": "x"}

    if host.endswith("reddit.com"):
        if m := re.search(r"/comments/([a-z0-9]+)", path):
            return {**out, "platform": "reddit", "kind": "post", "id": m.group(1)}
        if m := re.search(r"/(?:user|u)/([\w-]+)", path):
            return {**out, "platform": "reddit", "kind": "user", "id": m.group(1)}
        if path.startswith("/search") and _q(u, "q"):
            return {**out, "platform": "reddit", "kind": "keyword", "id": _q(u, "q")}
        return {**out, "platform": "reddit"}

    if host.endswith("zhihu.com"):
        if m := re.search(r"/answer/(\d+)", path):
            return {**out, "platform": "zhihu", "kind": "post", "id": f"answer:{m.group(1)}"}
        if host.startswith("zhuanlan.") and (m := re.match(r"/p/(\d+)", path)):
            return {**out, "platform": "zhihu", "kind": "post", "id": f"article:{m.group(1)}"}
        if m := re.match(r"/question/(\d+)", path):
            return {**out, "platform": "zhihu", "kind": "post", "id": f"question:{m.group(1)}"}
        if m := re.match(r"/people/([^/?#]+)", path):
            return {**out, "platform": "zhihu", "kind": "user", "id": m.group(1)}
        if path == "/search" and _q(u, "q"):
            return {**out, "platform": "zhihu", "kind": "keyword", "id": _q(u, "q")}
        return {**out, "platform": "zhihu"}

    if host.endswith("instagram.com"):
        if m := re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", u.path):
            return {**out, "platform": "instagram", "kind": "post", "id": m.group(1)}
        if u.path.startswith("/explore/search/") and _q(u, "q"):
            return {**out, "platform": "instagram", "kind": "keyword", "id": _q(u, "q")}
        if m := re.fullmatch(r"/([A-Za-z0-9_.]+)/?", u.path):
            if m.group(1) not in ("explore", "reels", "direct", "accounts", "stories"):
                return {**out, "platform": "instagram", "kind": "user", "id": m.group(1)}
        return {**out, "platform": "instagram"}
    if host.endswith("linkedin.com"):
        if m := re.search(r"/in/([^/?#]+)", u.path):
            return {**out, "platform": "linkedin", "kind": "user", "id": m.group(1)}
        if m := re.search(r"urn:li:(?:activity|ugcPost|share):(\d+)", u.path + "?" + (u.query or "")):
            return {**out, "platform": "linkedin", "kind": "post", "id": m.group(1)}
        if m := re.search(r"/posts/([^/?#]+)", u.path):
            return {**out, "platform": "linkedin", "kind": "post", "id": m.group(1)}
        if u.path.startswith("/search/") and _q(u, "keywords"):
            return {**out, "platform": "linkedin", "kind": "keyword", "id": _q(u, "keywords")}
        return {**out, "platform": "linkedin"}
    if host.endswith("toutiao.com"):
        if m := re.search(r"/(?:article|video|w|group|item|a)/?(\d{10,})", u.path):
            return {**out, "platform": "toutiao", "kind": "post", "id": m.group(1)}
        if m := re.search(r"/c/user/token/([^/?#]+)", u.path):
            return {**out, "platform": "toutiao", "kind": "user", "id": m.group(1)}
        if host.startswith("so.") and _q(u, "keyword"):
            return {**out, "platform": "toutiao", "kind": "keyword", "id": _q(u, "keyword")}
        return {**out, "platform": "toutiao"}
    if host.endswith("tiktok.com"):
        if m := re.search(r"/video/(\d+)", path):
            return {**out, "platform": "tiktok", "kind": "post", "id": m.group(1)}
        if m := re.match(r"/(@[\w.-]+)/?$", path):
            return {**out, "platform": "tiktok", "kind": "user", "id": m.group(1)}
        if path.startswith("/search") and _q(u, "q"):
            return {**out, "platform": "tiktok", "kind": "keyword", "id": _q(u, "q")}
        return {**out, "platform": "tiktok"}

    return out


@router.get("/resolve")
async def resolve_route(q: str = Query(min_length=1, max_length=2000)):
    """What is this: a link or id -> platform + kind (post | user | keyword | short_link) + id."""
    return ok(resolve(q))
