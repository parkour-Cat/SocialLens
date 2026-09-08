"""Raw Reddit `.json` payloads -> unified models.

Listings are {"kind": "Listing", "data": {"children": [{"kind": "t3"|"t1"|"t2", "data": {...}}], "after"}}.
A post page is a two-element array: [post listing, comment listing]. Comments carry their
`replies` as a nested listing (or "" when none).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "reddit"
SITE = "https://www.reddit.com"


def _ts(v: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat(timespec="seconds") if v else None
    except (TypeError, ValueError, OSError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _children(listing: Any, kind: str | None = None) -> list[dict]:
    if not isinstance(listing, dict):
        return []
    out = []
    for c in (listing.get("data") or {}).get("children") or []:
        if isinstance(c, dict) and isinstance(c.get("data"), dict) and (kind is None or c.get("kind") == kind):
            out.append(c["data"])
    return out


def _after(listing: Any) -> str | None:
    return (listing.get("data") or {}).get("after") if isinstance(listing, dict) else None


def _list_result(items: list, after: str | None) -> dict:
    return {"items": [i.model_dump() for i in items], "cursor": encode_cursor({"after": after}) if (after and items) else None, "total": None}


def _author(d: dict) -> SocialUser | None:
    name = d.get("author")
    if not name or name == "[deleted]":
        return None
    return SocialUser(id=str(name), platform=PLATFORM, name=name, url=f"{SITE}/user/{name}", raw={"fullname": d.get("author_fullname"), "flair": d.get("author_flair_text")})


def _unesc(u: Any) -> str | None:
    return html.unescape(u) if isinstance(u, str) and u else None


def _media(d: dict) -> list[MediaItem]:
    media: list[MediaItem] = []
    rv = ((d.get("media") or {}).get("reddit_video")) or ((d.get("secure_media") or {}).get("reddit_video")) or {}
    if rv.get("fallback_url"):
        url = str(rv["fallback_url"]).split("?")[0]
        base = url.rsplit("/", 1)[0]
        media.append(MediaItem(type="video", url=url, width=rv.get("width"), height=rv.get("height"), duration=float(rv.get("duration") or 0) or None, extra={"audio_url": f"{base}/DASH_AUDIO_128.mp4", "dash": rv.get("dash_url"), "hls": rv.get("hls_url"), "is_gif": rv.get("is_gif")}))
    meta = d.get("media_metadata") or {}
    if meta:
        order = [i.get("media_id") for i in ((d.get("gallery_data") or {}).get("items") or [])] or list(meta)
        for mid in order:
            m = meta.get(mid) or {}
            src = m.get("s") or {}
            u = _unesc(src.get("u") or src.get("gif") or src.get("mp4"))
            if u:
                media.append(MediaItem(type="video" if src.get("mp4") and not src.get("u") else "image", url=u, width=src.get("x"), height=src.get("y")))
    elif not media:
        hint = d.get("post_hint")
        url = _unesc(d.get("url_overridden_by_dest") or d.get("url"))
        if hint == "image" and url:
            src = (((d.get("preview") or {}).get("images") or [{}])[0].get("source")) or {}
            media.append(MediaItem(type="image", url=url, width=src.get("width"), height=src.get("height")))
        elif url and any(url.lower().split("?")[0].endswith(x) for x in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            media.append(MediaItem(type="image", url=url))
    return media


def _post(d: dict) -> SocialPost | None:
    if not d.get("id"):
        return None
    media = _media(d)
    thumb = _unesc(d.get("thumbnail")) if str(d.get("thumbnail", "")).startswith("http") else None
    preview = _unesc((((d.get("preview") or {}).get("images") or [{}])[0].get("source") or {}).get("url"))
    # SocialPost.type has no "link": external-link posts are "article" (raw.link_url keeps the target).
    kind = "video" if any(m.type == "video" for m in media) else ("image" if media else ("article" if d.get("post_hint") == "link" or (not d.get("is_self") and not media) else "text"))
    return SocialPost(
        id=str(d["id"]),
        platform=PLATFORM,
        type=kind,
        title=d.get("title"),
        content=d.get("selftext") or None,
        author=_author(d),
        url=SITE + d["permalink"] if d.get("permalink") else _unesc(d.get("url")),
        cover_url=preview or thumb,
        media=media,
        metrics=Metrics(likes=_int(d.get("score")), comments=_int(d.get("num_comments")), shares=_int(d.get("num_crossposts")), views=_int(d.get("view_count"))),
        publish_time=_ts(d.get("created_utc")),
        tags=[t for t in [d.get("link_flair_text")] if t],
        raw={
            "subreddit": d.get("subreddit"),
            "fullname": d.get("name"),
            "upvote_ratio": d.get("upvote_ratio"),
            "ups": d.get("ups"),
            "over_18": d.get("over_18"),
            "spoiler": d.get("spoiler"),
            "is_self": d.get("is_self"),
            "link_url": _unesc(d.get("url_overridden_by_dest")) if not d.get("is_self") else None,
            "domain": d.get("domain"),
            "awards": _int(d.get("total_awards_received")),
            "gallery": bool(d.get("media_metadata")),
        },
    )


def _user(d: dict) -> SocialUser | None:
    name = d.get("name")
    if not name:
        return None
    sub = d.get("subreddit") or {}
    return SocialUser(
        id=str(name),
        platform=PLATFORM,
        name=sub.get("title") or name,
        avatar_url=_unesc(d.get("icon_img") or sub.get("icon_img")),
        url=f"{SITE}/user/{name}",
        bio=sub.get("public_description") or None,
        metrics=UserMetrics(followers=_int(sub.get("subscribers")), posts=None),
        raw={"fullname": d.get("id"), "total_karma": _int(d.get("total_karma")) or ((_int(d.get("link_karma")) or 0) + (_int(d.get("comment_karma")) or 0) or None), "link_karma": _int(d.get("link_karma")), "comment_karma": _int(d.get("comment_karma")), "created": _ts(d.get("created_utc")), "verified": d.get("verified"), "is_mod": d.get("is_mod"), "is_gold": d.get("is_gold")},
    )


def _comment(d: dict, post_id: str, parent_id: str | None = None) -> SocialComment | None:
    if not d.get("id") or d.get("body") is None:
        return None
    return SocialComment(
        id=str(d["id"]),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=_author(d),
        content=d.get("body"),
        likes=_int(d.get("score")),
        publish_time=_ts(d.get("created_utc")),
        raw={"depth": d.get("depth"), "reply_count": (len(_children(d.get("replies"), "t1")) or None) if isinstance(d.get("replies"), dict) else None, "has_more_replies": any(c.get("kind") == "more" for c in (((d.get("replies") or {}).get("data") or {}).get("children") or []) if isinstance(c, dict)) if isinstance(d.get("replies"), dict) else False, "is_submitter": d.get("is_submitter"), "stickied": d.get("stickied"), "awards": _int(d.get("total_awards_received"))},
    )


# ---- actions -------------------------------------------------------------------------------------


def parse_search_posts(raw: Any) -> dict:
    return _list_result([p for d in _children(raw, "t3") if (p := _post(d))], _after(raw))


parse_get_user_posts = parse_search_posts
parse_get_feed = parse_search_posts


def parse_get_trending(raw: Any) -> dict:
    out = parse_search_posts(raw)
    out["kind"] = "posts"
    return out


def parse_search_users(raw: Any) -> dict:
    return _list_result([u for d in _children(raw, "t2") if (u := _user(d))], _after(raw))


def parse_get_post(raw: Any) -> dict:
    listing = raw[0] if isinstance(raw, list) and raw else raw
    posts = [p for d in _children(listing, "t3") if (p := _post(d))]
    if not posts:
        raise ValueError("post not found (removed, or page changed)")
    return posts[0].model_dump()


def parse_get_user(raw: Any) -> dict:
    d = (raw.get("data") if isinstance(raw, dict) else None) or {}
    u = _user(d)
    if not u:
        raise ValueError("user not found (suspended, or page changed)")
    return u.model_dump()


def _more_ids(listing: Any) -> list[str]:
    """Ids named by the top-level "more" stub of a comment listing (depth 0 only)."""
    ids: list[str] = []
    for c in (listing.get("data") or {}).get("children") or [] if isinstance(listing, dict) else []:
        if isinstance(c, dict) and c.get("kind") == "more" and (c.get("data") or {}).get("depth", 0) == 0:
            ids.extend(str(x) for x in (c["data"].get("children") or []))
    return ids


def parse_get_comments(raw: Any) -> dict:
    # page 2+: /api/morechildren -> {"json": {"data": {"things": [{"kind": "t1"|"more", "data": {...}}]}}}
    if isinstance(raw, dict) and isinstance(raw.get("json"), dict):
        things = ((raw["json"].get("data") or {}).get("things")) or []
        items: list[SocialComment] = []
        link = ""
        for t in things:
            d = t.get("data") if isinstance(t, dict) else None
            if not isinstance(d, dict) or t.get("kind") != "t1":
                continue
            link = link or str(d.get("link_id") or "").replace("t3_", "")
            parent = str(d.get("parent_id") or "")
            c = _comment(d, link, parent_id=parent.replace("t1_", "") if parent.startswith("t1_") else None)
            if c:
                items.append(c)
        rest = raw.get("_rest") if isinstance(raw.get("_rest"), list) else []
        return {"items": [c.model_dump() for c in items], "cursor": encode_cursor({"children": rest}) if rest else None, "total": None}
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("expected [post listing, comment listing]")
    post_id = str((_children(raw[0], "t3") or [{}])[0].get("id") or "")
    items = []
    for d in _children(raw[1], "t1"):
        c = _comment(d, post_id)
        if c:
            items.append(c)
    more = _more_ids(raw[1])
    return {"items": [c.model_dump() for c in items], "cursor": encode_cursor({"children": more}) if more else None, "total": _int((_children(raw[0], "t3") or [{}])[0].get("num_comments"))}


def parse_get_replies(raw: Any) -> dict:
    """/comments/{post}/_/{comment}.json: the focal comment (with its replies nested) as the only t1 child."""
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("expected [post listing, comment listing]")
    post_id = str((_children(raw[0], "t3") or [{}])[0].get("id") or "")
    focal = (_children(raw[1], "t1") or [None])[0]
    if not focal:
        raise ValueError("comment not found")
    items: list[SocialComment] = []
    for d in _children(focal.get("replies"), "t1"):
        c = _comment(d, post_id, parent_id=str(focal.get("id")))
        if c:
            items.append(c)
    return {"items": [c.model_dump() for c in items], "cursor": None, "total": len(items) or None}
