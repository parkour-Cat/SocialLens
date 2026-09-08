"""Raw X payloads -> unified models.

Payloads are Capture objects whose `body` is a GraphQL timeline response. Tweets are found by
walking for {"__typename": "Tweet", "legacy": {...}}; users by {"__typename": "User"} (the
2026 layout keeps name/screen_name under `core`, counts under `relationship_counts` /
`tweet_counts`, bio under `profile_bio`).
"""

from __future__ import annotations

import re

from datetime import datetime
from typing import Any, Callable

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "x"
SITE = "https://x.com"


def _walk(obj: Any, pred: Callable[[dict], bool], depth: int = 0, out: list | None = None) -> list[dict]:
    out = out if out is not None else []
    if depth > 80:
        return out
    if isinstance(obj, dict):
        if pred(obj):
            out.append(obj)
            return out
        for v in obj.values():
            _walk(v, pred, depth + 1, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, pred, depth + 1, out)
    return out


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _time(v: Any) -> str | None:
    """'Mon Sep 07 08:54:47 +0000 2026' -> ISO."""
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%a %b %d %H:%M:%S %z %Y").isoformat()
    except ValueError:
        return None


def _body(raw: Any) -> Any:
    if isinstance(raw, dict) and raw.get("end") is True:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    return raw


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _has_bottom_cursor(body: Any) -> bool:
    return bool(_walk(body, lambda d: d.get("cursorType") == "Bottom" and bool(d.get("value"))))


def _list_result(items: list, tab: int | None, has_more: bool) -> dict:
    return {"items": [p.model_dump() for p in items], "cursor": encode_cursor({"tab": tab}) if (has_more and tab and items) else None, "total": None}


def _user(u: Any) -> SocialUser | None:
    if not isinstance(u, dict):
        return None
    core = u.get("core") or {}
    legacy = u.get("legacy") or {}
    screen = core.get("screen_name") or legacy.get("screen_name")
    if not screen:
        return None
    rel = u.get("relationship_counts") or {}
    tc = u.get("tweet_counts") or {}
    bio = (u.get("profile_bio") or {}).get("description") or legacy.get("description")
    avatar = (u.get("avatar") or {}).get("image_url") or legacy.get("profile_image_url_https")
    return SocialUser(
        id=str(screen),
        platform=PLATFORM,
        name=core.get("name") or legacy.get("name"),
        avatar_url=avatar.replace("_normal.", "_400x400.") if isinstance(avatar, str) else None,
        url=f"{SITE}/{screen}",
        bio=bio,
        metrics=UserMetrics(
            followers=_int(rel.get("followers")) or _int(legacy.get("followers_count")),
            following=_int(rel.get("following")) or _int(legacy.get("friends_count")),
            posts=_int(tc.get("tweets")) or _int(legacy.get("statuses_count")),
        ),
        raw={
            "rest_id": u.get("rest_id"),
            "created_at": _time(core.get("created_at") or legacy.get("created_at")),
            "location": (u.get("location") or {}).get("location") or legacy.get("location"),
            "blue_verified": u.get("is_blue_verified"),
            "verified_type": (u.get("verification") or {}).get("verified_type"),
            "media_tweets": _int(tc.get("media_tweets")),
        },
    )


def _tweet(t: dict) -> SocialPost | None:
    legacy = t.get("legacy") or {}
    tid = t.get("rest_id") or legacy.get("id_str")
    if not tid:
        return None
    author = _user(((t.get("core") or {}).get("user_results") or {}).get("result"))
    text = (t.get("note_tweet") or {}).get("note_tweet_results", {}).get("result", {}).get("text") or legacy.get("full_text")
    media: list[MediaItem] = []
    for m in (legacy.get("extended_entities") or legacy.get("entities") or {}).get("media") or []:
        if not isinstance(m, dict):
            continue
        if m.get("type") in ("video", "animated_gif"):
            variants = [v for v in (m.get("video_info") or {}).get("variants") or [] if isinstance(v, dict) and v.get("content_type") == "video/mp4"]
            best = max(variants, key=lambda v: v.get("bitrate") or 0, default=None)
            if best:
                size = m.get("original_info") or {}
                media.append(MediaItem(type="video", url=best["url"], width=size.get("width"), height=size.get("height"), duration=((m.get("video_info") or {}).get("duration_millis") or 0) / 1000 or None, extra={"bitrate": best.get("bitrate"), "cover": m.get("media_url_https")}))
        elif m.get("media_url_https"):
            size = m.get("original_info") or {}
            media.append(MediaItem(type="image", url=m["media_url_https"] + "?name=orig", width=size.get("width"), height=size.get("height")))
    views = _int((t.get("views") or {}).get("count"))
    screen = author.id if author else None
    return SocialPost(
        id=str(tid),
        platform=PLATFORM,
        type="video" if any(m.type == "video" for m in media) else ("image" if media else "text"),
        title=None,
        content=text,
        author=author,
        url=f"{SITE}/{screen}/status/{tid}" if screen else f"{SITE}/i/status/{tid}",
        cover_url=media[0].extra.get("cover") if media and media[0].type == "video" else (media[0].url if media else None),
        media=media,
        metrics=Metrics(
            likes=_int(legacy.get("favorite_count")),
            comments=_int(legacy.get("reply_count")),
            shares=(_int(legacy.get("retweet_count")) or 0) + (_int(legacy.get("quote_count")) or 0) or None,
            collects=_int(legacy.get("bookmark_count")),
            views=views,
        ),
        publish_time=_time(legacy.get("created_at")),
        tags=[h.get("text") for h in (legacy.get("entities") or {}).get("hashtags") or [] if isinstance(h, dict) and h.get("text")],
        raw={
            "lang": legacy.get("lang"),
            "conversation_id": legacy.get("conversation_id_str"),
            "in_reply_to": legacy.get("in_reply_to_status_id_str"),
            "retweets": _int(legacy.get("retweet_count")),
            "quotes": _int(legacy.get("quote_count")),
            "is_quote": legacy.get("is_quote_status"),
            "source": t.get("source"),
        },
    )


def _tweets(raw: Any) -> list[SocialPost]:
    seen: set[str] = set()
    out: list[SocialPost] = []
    for t in _walk(_body(raw), lambda d: d.get("__typename") == "Tweet" and isinstance(d.get("legacy"), dict)):
        p = _tweet(t)
        if p and p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out


def parse_search_posts(raw: Any) -> dict:
    return _list_result(_tweets(raw), _tab(raw), _has_bottom_cursor(_body(raw)))


parse_get_user_posts = parse_search_posts
parse_get_feed = parse_search_posts


def parse_search_users(raw: Any) -> dict:
    users = [u for d in _walk(_body(raw), lambda d: d.get("__typename") == "User" and ("core" in d or "legacy" in d)) if (u := _user(d))]
    return _list_result(users, _tab(raw), _has_bottom_cursor(_body(raw)))


def parse_get_user(raw: Any) -> dict:
    found = _walk(_body(raw), lambda d: d.get("__typename") == "User" and ("core" in d or "legacy" in d))
    u = _user(found[0]) if found else None
    if not u:
        raise ValueError("user not found (suspended, private, or page changed)")
    return u.model_dump()


def _focal_id(raw: Any) -> str | None:
    url = raw.get("url", "") if isinstance(raw, dict) else ""
    if "focalTweetId" in url:
        import urllib.parse

        q = urllib.parse.unquote(url.split("variables=")[1].split("&")[0]) if "variables=" in url else ""
        if '"focalTweetId":"' in q:
            return q.split('"focalTweetId":"')[1].split('"')[0]
    return None


def parse_get_post(raw: Any) -> dict:
    tweets = _tweets(raw)
    if not tweets:
        raise ValueError("tweet not found (deleted, protected, or page changed)")
    focal = _focal_id(raw)
    for t in tweets:
        if t.id == focal:
            return t.model_dump()
    return tweets[0].model_dump()


def parse_get_comments(raw: Any) -> dict:
    tweets = _tweets(raw)
    focal = _focal_id(raw) or (tweets[0].id if tweets else "")
    items: list[SocialComment] = []
    for t in tweets:
        if t.id == focal:
            continue
        items.append(
            SocialComment(
                id=t.id,
                platform=PLATFORM,
                post_id=focal,
                parent_id=t.raw.get("in_reply_to") if t.raw.get("in_reply_to") not in (None, focal) else None,
                author=t.author,
                content=t.content,
                likes=t.metrics.likes,
                publish_time=t.publish_time,
                raw={"url": t.url, "replies": t.metrics.comments},
            )
        )
    return _list_result(items, _tab(raw), _has_bottom_cursor(_body(raw)))


def parse_get_replies(raw: Any) -> dict:
    """Replies to a reply are the comments of that reply's own TweetDetail page."""
    out = parse_get_comments(raw)
    focal = _focal_id(raw)
    for c in out["items"]:
        c["parent_id"] = c.get("parent_id") or focal
        conv = (c.get("raw") or {}).get("conversation_id")
        if conv:
            c["post_id"] = str(conv)
    return out


def _heat(desc: Any) -> int | None:
    """'12.3K posts' / '1.2万 帖子' -> 12300 / 12000."""
    m = re.search(r"([\d.,]+)\s*([KkMm万亿]?)", str(desc or ""))
    if not m or not m.group(1).replace(",", "").replace(".", "").isdigit():
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n * {"k": 1e3, "m": 1e6, "万": 1e4, "亿": 1e8}.get(m.group(2).lower(), 1))


def parse_get_trending(raw: Any) -> dict:
    """Explore / trending timeline: TimelineTrend items with name, trend_url, rank and metadata."""
    body = _body(raw)
    items = []
    for i, d in enumerate(_walk(body, lambda d: d.get("itemType") == "TimelineTrend" or d.get("__typename") == "TimelineTrend")):
        name = d.get("name")
        if not name:
            continue
        meta = d.get("trend_metadata") or d.get("trendMetadata") or {}
        url = ((d.get("trend_url") or {}).get("url") or "").replace("twitter://search/?query=", "")
        items.append({
            "rank": _int(d.get("rank")) or i + 1,
            "type": "topic",
            "platform": PLATFORM,
            "title": name,
            "url": f"{SITE}/search?q={url or name}&src=trend_click" if not str(url).startswith("http") else url,
            "heat": _heat(meta.get("meta_description")),
            "description": meta.get("meta_description"),
            "category": meta.get("domain_context"),
            "raw": {"meta": meta},
        })
    return {"items": items, "cursor": None, "total": len(items) or None, "kind": "topics"}

