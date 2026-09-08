"""Raw B 站 JSON -> unified models. Pure functions; tested against tests/fixtures/bilibili/.

List actions return {"items": [...], "cursor": str | None, "total": int | None}.
Single-object actions return the model as a dict. Fields the platform lacks stay None.
"""

from __future__ import annotations

import html

import re
from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from .cursor import encode_cursor

PLATFORM = "bilibili"
_TAG_RE = re.compile(r"<[^>]+>")


# ---- helpers -----------------------------------------------------------------


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> str | None:
    n = _int(v)
    if not n:
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")


def _url(v: Any) -> str | None:
    if not v:
        return None
    s = str(v)
    return "https:" + s if s.startswith("//") else s


def _clean(v: Any) -> str | None:
    """Search results carry <em class="keyword"> highlights and HTML entities (&#x27;, &amp;)."""
    return html.unescape(_TAG_RE.sub("", str(v))) if v is not None else None


def _duration(v: Any) -> float | None:
    """Accepts seconds or 'mm:ss' / 'hh:mm:ss' strings."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    parts = [p for p in str(v).split(":") if p != ""]
    try:
        total = 0.0
        for p in parts:
            total = total * 60 + float(p)
        return total
    except ValueError:
        return None


def _video_url(bvid: str | None, aid: Any = None) -> str | None:
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}/"
    if aid:
        return f"https://www.bilibili.com/video/av{aid}/"
    return None


def _user_url(mid: Any) -> str | None:
    return f"https://space.bilibili.com/{mid}" if mid else None


def _author(mid: Any, name: Any, face: Any = None) -> SocialUser | None:
    if not mid:
        return None
    return SocialUser(id=str(mid), platform=PLATFORM, name=name, avatar_url=_url(face), url=_user_url(mid))


def _data(raw: Any) -> dict:
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        return raw["data"]
    raise ValueError("unexpected response shape: missing data object")


# ---- search ------------------------------------------------------------------


def _search_video(item: dict) -> SocialPost:
    bvid = item.get("bvid")
    tags = [t for t in str(item.get("tag") or "").split(",") if t]
    return SocialPost(
        id=str(bvid or item.get("aid")),
        platform=PLATFORM,
        type="video",
        title=_clean(item.get("title")),
        content=item.get("description"),
        author=_author(item.get("mid"), item.get("author"), item.get("upic")),
        url=_video_url(bvid, item.get("aid")),
        cover_url=_url(item.get("pic")),
        metrics=Metrics(
            likes=_int(item.get("like")),
            comments=_int(item.get("review")),
            collects=_int(item.get("favorites")),
            views=_int(item.get("play")),
        ),
        publish_time=_ts(item.get("pubdate")),
        tags=tags,
        raw={"aid": item.get("aid"), "duration": item.get("duration"), "typename": item.get("typename"), "danmaku": item.get("danmaku")},
    )


def _search_user(item: dict) -> SocialUser:
    return SocialUser(
        id=str(item.get("mid")),
        platform=PLATFORM,
        name=item.get("uname"),
        avatar_url=_url(item.get("upic")),
        url=_user_url(item.get("mid")),
        bio=item.get("usign"),
        metrics=UserMetrics(followers=_int(item.get("fans")), posts=_int(item.get("videos"))),
        raw={"level": item.get("level"), "official_verify": item.get("official_verify")},
    )


def _search_cursor(d: dict) -> str | None:
    page, pages = _int(d.get("page")) or 1, _int(d.get("numPages")) or 1
    return encode_cursor({"page": page + 1}) if page < pages else None


def parse_search_posts(raw: Any) -> dict:
    d = _data(raw)
    items = [_search_video(r).model_dump() for r in d.get("result") or [] if r.get("type") == "video"]
    return {"items": items, "cursor": _search_cursor(d), "total": _int(d.get("numResults"))}


def parse_search_users(raw: Any) -> dict:
    d = _data(raw)
    items = [_search_user(r).model_dump() for r in d.get("result") or [] if r.get("type") == "bili_user"]
    return {"items": items, "cursor": _search_cursor(d), "total": _int(d.get("numResults"))}


# ---- post ----------------------------------------------------------------------


def parse_get_post(raw: Any) -> dict:
    d = _data(raw)
    owner = d.get("owner") or {}
    stat = d.get("stat") or {}
    pages = d.get("pages") or []
    media = [
        MediaItem(
            type="video",
            url=_video_url(d.get("bvid"), d.get("aid")) or "",
            duration=_duration(p.get("duration")),
            width=(p.get("dimension") or {}).get("width"),
            height=(p.get("dimension") or {}).get("height"),
            headers={"Referer": "https://www.bilibili.com/"},
            extra={"cid": p.get("cid"), "page": p.get("page"), "part": p.get("part"), "needs_playurl": True},
        )
        for p in pages
    ]
    tags = [d["tname"]] if d.get("tname") else []
    return SocialPost(
        id=str(d.get("bvid") or d.get("aid")),
        platform=PLATFORM,
        type="video",
        title=d.get("title"),
        content=d.get("desc"),
        author=_author(owner.get("mid"), owner.get("name"), owner.get("face")),
        url=_video_url(d.get("bvid"), d.get("aid")),
        cover_url=_url(d.get("pic")),
        media=media,
        metrics=Metrics(
            likes=_int(stat.get("like")),
            comments=_int(stat.get("reply")),
            shares=_int(stat.get("share")),
            collects=_int(stat.get("favorite")),
            views=_int(stat.get("view")),
        ),
        publish_time=_ts(d.get("pubdate")),
        tags=tags,
        raw={
            "aid": d.get("aid"),
            "cid": d.get("cid"),
            "duration": d.get("duration"),
            "coin": stat.get("coin"),
            "danmaku": stat.get("danmaku"),
            "copyright": d.get("copyright"),
            "videos": d.get("videos"),
        },
    ).model_dump()


# ---- user ----------------------------------------------------------------------


def parse_get_user(raw: Any) -> dict:
    if not isinstance(raw, dict) or "info" not in raw:
        raise ValueError("expected {info, stat}")
    info = _data(raw["info"])
    stat = raw.get("stat", {}).get("data") or {}
    return SocialUser(
        id=str(info.get("mid")),
        platform=PLATFORM,
        name=info.get("name"),
        avatar_url=_url(info.get("face")),
        url=_user_url(info.get("mid")),
        bio=info.get("sign"),
        metrics=UserMetrics(followers=_int(stat.get("follower")), following=_int(stat.get("following"))),
        raw={
            "level": info.get("level"),
            "sex": info.get("sex"),
            "official": info.get("official"),
            "vip": (info.get("vip") or {}).get("status"),
            "top_photo": _url(info.get("top_photo")),
        },
    ).model_dump()


# ---- comments ------------------------------------------------------------------


def _comment(item: dict, post_id: str) -> SocialComment:
    member = item.get("member") or {}
    parent = item.get("parent")
    return SocialComment(
        id=str(item.get("rpid")),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=str(parent) if parent else None,
        author=_author(member.get("mid") or item.get("mid"), member.get("uname"), member.get("avatar")),
        content=(item.get("content") or {}).get("message"),
        likes=_int(item.get("like")),
        publish_time=_ts(item.get("ctime")),
        raw={"rcount": item.get("rcount"), "reply_control": (item.get("reply_control") or {}).get("location")},
    )


def parse_get_comments(raw: Any) -> dict:
    d = _data(raw)
    # The page action attaches the id the caller used; fall back to the aid carried by replies.
    roots = list(d.get("top_replies") or []) + list(d.get("replies") or [])
    post_id = str(raw.get("_post_id") or (roots[0].get("oid") if roots else "") or "")
    items: list[dict] = []
    seen: set[str] = set()
    for r in roots:
        for entry in [r, *(r.get("replies") or [])]:
            c = _comment(entry, post_id)
            if c.id in seen:
                continue
            seen.add(c.id)
            items.append(c.model_dump())
    cursor_info = d.get("cursor") or {}
    next_offset = (cursor_info.get("pagination_reply") or {}).get("next_offset")
    cursor = encode_cursor({"offset": next_offset}) if next_offset and not cursor_info.get("is_end") else None
    return {"items": items, "cursor": cursor, "total": _int(cursor_info.get("all_count"))}


# ---- user posts ----------------------------------------------------------------


def parse_get_user_posts(raw: Any) -> dict:
    d = _data(raw)
    vlist = (d.get("list") or {}).get("vlist") or []
    items = []
    for v in vlist:
        items.append(
            SocialPost(
                id=str(v.get("bvid") or v.get("aid")),
                platform=PLATFORM,
                type="video",
                title=v.get("title"),
                content=v.get("description"),
                author=_author(v.get("mid"), v.get("author")),
                url=_video_url(v.get("bvid"), v.get("aid")),
                cover_url=_url(v.get("pic")),
                metrics=Metrics(comments=_int(v.get("comment")), views=_int(v.get("play"))),
                publish_time=_ts(v.get("created")),
                raw={"aid": v.get("aid"), "length": v.get("length"), "danmaku": v.get("video_review"), "typeid": v.get("typeid")},
            ).model_dump()
        )
    page = d.get("page") or {}
    pn, ps, count = _int(page.get("pn")) or 1, _int(page.get("ps")) or 30, _int(page.get("count")) or 0
    cursor = encode_cursor({"page": pn + 1}) if pn * ps < count else None
    return {"items": items, "cursor": cursor, "total": count}


# ---- playurl (download) ------------------------------------------------------------


def parse_get_play_url(raw: Any) -> dict:
    """Passthrough of playurl `data` (dash or durl); the picker below reads it."""
    return _data(raw)


def pick_play_source(play: Any, mode: str) -> dict | None:
    """Choose streams from a playurl payload.

    dash: highest-quality video (prefer AVC for player compatibility at equal quality) plus the
    highest-bandwidth audio, merged later with ffmpeg. mp4/durl: the first (single) segment.
    """
    if not isinstance(play, dict):
        return None
    referer = {"Referer": "https://www.bilibili.com/"}
    dash = play.get("dash") if mode == "dash" else None
    if isinstance(dash, dict) and dash.get("video"):
        videos = [v for v in dash["video"] if isinstance(v, dict) and (v.get("baseUrl") or v.get("base_url"))]
        videos.sort(key=lambda v: (int(v.get("id") or 0), 1 if int(v.get("codecid") or 0) == 7 else 0, int(v.get("bandwidth") or 0)), reverse=True)
        audios = [a for a in dash.get("audio") or [] if isinstance(a, dict) and (a.get("baseUrl") or a.get("base_url"))]
        audios.sort(key=lambda a: int(a.get("bandwidth") or 0), reverse=True)
        if videos:
            v = videos[0]
            parts = [{"url": v.get("baseUrl") or v.get("base_url"), "backup_urls": v.get("backupUrl") or v.get("backup_url") or [], "headers": referer, "ext": "m4s"}]
            if audios:
                a = audios[0]
                parts.append({"url": a.get("baseUrl") or a.get("base_url"), "backup_urls": a.get("backupUrl") or a.get("backup_url") or [], "headers": referer, "ext": "m4s"})
            return {"type": "video", "url": parts[0]["url"], "parts": parts, "ext": "mp4", "quality": v.get("id"), "width": v.get("width"), "height": v.get("height")}
    durl = play.get("durl") or []
    if durl and isinstance(durl[0], dict) and durl[0].get("url"):
        return {"type": "video", "url": durl[0]["url"], "backup_urls": durl[0].get("backup_url") or [], "ext": "mp4", "quality": play.get("quality"), "segments": len(durl)}
    return None


# ---- replies / trending --------------------------------------------------------------------


def parse_get_replies(raw: Any) -> dict:
    """/x/v2/reply/reply: data.replies[] under data.page {num, size, count}."""
    d = _data(raw)
    post_id = str(raw.get("_post_id") or "")
    root = str(raw.get("_comment_id") or (d.get("root") or {}).get("rpid") or "")
    items = []
    for r in d.get("replies") or []:
        if isinstance(r, dict):
            c = _comment(r, post_id)
            c.parent_id = root
            items.append(c.model_dump())
    page = d.get("page") or {}
    num, size, count = _int(page.get("num")) or 1, _int(page.get("size")) or 20, _int(page.get("count")) or 0
    cursor = encode_cursor({"page": num + 1}) if items and num * size < count else None
    return {"items": items, "cursor": cursor, "total": count or None}


def parse_get_trending(raw: Any) -> dict:
    """/x/web-interface/popular: data.list[] (view-like records), data.no_more."""
    d = _data(raw)
    items = []
    for i, v in enumerate(d.get("list") or []):
        if not isinstance(v, dict):
            continue
        owner = v.get("owner") or {}
        stat = v.get("stat") or {}
        items.append(
            SocialPost(
                id=str(v.get("bvid") or v.get("aid")),
                platform=PLATFORM,
                type="video",
                title=v.get("title"),
                content=v.get("desc"),
                author=_author(owner.get("mid"), owner.get("name"), owner.get("face")),
                url=_video_url(v.get("bvid"), v.get("aid")),
                cover_url=_url(v.get("pic")),
                metrics=Metrics(likes=_int(stat.get("like")), comments=_int(stat.get("reply")), shares=_int(stat.get("share")), collects=_int(stat.get("favorite")), views=_int(stat.get("view"))),
                publish_time=_ts(v.get("pubdate")),
                tags=[v["tname"]] if v.get("tname") else [],
                raw={"aid": v.get("aid"), "cid": v.get("cid"), "duration": v.get("duration"), "rcmd_reason": (v.get("rcmd_reason") or {}).get("content"), "danmaku": _int(stat.get("danmaku")), "coin": _int(stat.get("coin"))},
            ).model_dump()
        )
    page = _int(raw.get("_page")) or 1
    cursor = encode_cursor({"page": page + 1}) if items and not d.get("no_more") else None
    return {"items": items, "cursor": cursor, "total": None, "kind": "posts"}

