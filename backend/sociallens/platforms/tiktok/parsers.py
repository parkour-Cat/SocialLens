"""Raw TikTok payloads -> unified models.

Videos are `itemStruct`-shaped: {id, desc, createTime, author{uniqueId, nickname, avatarLarger,
signature}, authorStats{followerCount,...}, stats{diggCount, commentCount, shareCount, playCount,
collectCount}, video{cover, playAddr, duration, width, height}, challenges[{title}]}. Lists put them
in `itemList` (feed / user posts) or `data[].item` (search). Field names are from public knowledge
and MUST be re-checked against fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "tiktok"
SITE = "https://www.tiktok.com"


def _walk(obj: Any, pred: Callable[[dict], bool], depth: int = 0, out: list | None = None) -> list[dict]:
    out = out if out is not None else []
    if depth > 60:
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


def _ts(v: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat(timespec="seconds") if v else None
    except (TypeError, ValueError, OSError):
        return None


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _body(raw: Any) -> dict:
    if isinstance(raw, dict) and raw.get("end") is True:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    return raw if isinstance(raw, dict) else {}


def _list_result(items: list, has_more: Any, tab: int | None) -> dict:
    return {"items": [i.model_dump() for i in items], "cursor": encode_cursor({"tab": tab}) if (has_more and tab and items) else None, "total": None}


def _user(a: Any, stats: Any = None) -> SocialUser | None:
    if not isinstance(a, dict) or not (a.get("uniqueId") or a.get("unique_id")):
        return None
    uid = a.get("uniqueId") or a.get("unique_id")
    st = stats if isinstance(stats, dict) else (a.get("stats") or {})
    return SocialUser(
        id=str(uid),
        platform=PLATFORM,
        name=a.get("nickname"),
        avatar_url=a.get("avatarLarger") or a.get("avatarMedium") or a.get("avatarThumb"),
        url=f"{SITE}/@{uid}",
        bio=a.get("signature") or None,
        metrics=UserMetrics(followers=_int(st.get("followerCount")), following=_int(st.get("followingCount")), posts=_int(st.get("videoCount"))),
        raw={"sec_uid": a.get("secUid"), "user_id": a.get("id"), "verified": a.get("verified"), "hearts": _int(st.get("heartCount") or st.get("heart")), "region": a.get("region")},
    )


def _post(it: dict) -> SocialPost | None:
    if not isinstance(it, dict) or not it.get("id") or "video" not in it and "desc" not in it:
        return None
    v = it.get("video") or {}
    st = it.get("stats") or it.get("statsV2") or {}
    author = _user(it.get("author"), it.get("authorStats"))
    uid = author.id if author else "tiktok"
    play = v.get("playAddr") or v.get("downloadAddr")
    media = [MediaItem(type="video", url=play, width=_int(v.get("width")), height=_int(v.get("height")), duration=float(v.get("duration") or 0) or None, extra={"cookie_bound": True, "needs_stream_resolution": True, "bitrate": v.get("bitrate"), "format": v.get("format")})] if play else []
    images = ((it.get("imagePost") or {}).get("images") or [])
    for im in images:
        urls = ((im.get("imageURL") or {}).get("urlList")) or []
        if urls:
            media.append(MediaItem(type="image", url=urls[0], width=_int(im.get("imageWidth")), height=_int(im.get("imageHeight"))))
    return SocialPost(
        id=str(it["id"]),
        platform=PLATFORM,
        type="image" if images else "video",
        title=None,
        content=it.get("desc"),
        author=author,
        url=f"{SITE}/@{uid}/video/{it['id']}",
        cover_url=v.get("cover") or v.get("originCover") or v.get("dynamicCover"),
        media=media,
        metrics=Metrics(likes=_int(st.get("diggCount")), comments=_int(st.get("commentCount")), shares=_int(st.get("shareCount")), collects=_int(st.get("collectCount")), views=_int(st.get("playCount"))),
        publish_time=_ts(it.get("createTime")),
        tags=[c.get("title") for c in it.get("challenges") or [] if isinstance(c, dict) and c.get("title")],
        raw={"music": (it.get("music") or {}).get("title"), "duet_enabled": it.get("duetEnabled"), "is_ad": it.get("isAd"), "location": (it.get("locationCreated") or None)},
    )


def _items(b: dict) -> list[dict]:
    for key in ("itemList", "item_list"):  # feed / user posts / explore vs search
        if isinstance(b.get(key), list):
            return [x for x in b[key] if isinstance(x, dict)]
    out = []
    for d in b.get("data") or []:
        if isinstance(d, dict):
            it = d.get("item") or (d if "id" in d and ("video" in d or "desc" in d) else None)
            if isinstance(it, dict):
                out.append(it)
    return out


def parse_search_posts(raw: Any) -> dict:
    b = _body(raw)
    return _list_result([p for it in _items(b) if (p := _post(it))], b.get("has_more") or b.get("hasMore"), _tab(raw))


parse_get_feed = parse_search_posts
parse_get_user_posts = parse_search_posts


def parse_get_trending(raw: Any) -> dict:
    out = parse_search_posts(raw)
    out["kind"] = "posts"
    return out


def parse_search_users(raw: Any) -> dict:
    b = _body(raw)
    items = []
    for d in b.get("user_list") or b.get("data") or []:
        info = (d.get("user_info") or d.get("user") or d) if isinstance(d, dict) else None
        u = _user({"uniqueId": info.get("unique_id") or info.get("uniqueId"), "nickname": info.get("nickname"), "avatarLarger": (info.get("avatar_larger") or {}).get("url_list", [None])[0] if isinstance(info.get("avatar_larger"), dict) else info.get("avatarLarger"), "signature": info.get("signature"), "secUid": info.get("sec_uid") or info.get("secUid"), "id": info.get("uid") or info.get("id"), "stats": {"followerCount": info.get("follower_count"), "heartCount": info.get("total_favorited"), "videoCount": info.get("aweme_count")}}) if isinstance(info, dict) else None
        if u:
            items.append(u)
    return _list_result(items, b.get("has_more") or b.get("hasMore"), _tab(raw))


def _rehydrated(raw: Any) -> dict:
    """The page hands over the raw text of the rehydration script; older payloads carry `data`."""
    data = raw.get("data") if isinstance(raw, dict) else None
    if data is None and isinstance(raw, dict) and isinstance(raw.get("text"), str):
        import json

        try:
            data = json.loads(raw["text"])
        except ValueError:
            data = None
    return (data or {}).get("__DEFAULT_SCOPE__") or data or {}


def parse_get_post(raw: Any) -> dict:
    scope = _rehydrated(raw)
    it = ((scope.get("webapp.video-detail") or {}).get("itemInfo") or {}).get("itemStruct")
    if not isinstance(it, dict):
        found = _walk(scope, lambda d: isinstance(d.get("itemStruct"), dict))
        it = found[0]["itemStruct"] if found else None
    p = _post(it) if isinstance(it, dict) else None
    if not p:
        status = (scope.get("webapp.video-detail") or {}).get("statusCode")
        raise ValueError(f"video not found in rehydration state (statusCode={status}; removed, private, or page changed)")
    return p.model_dump()


def parse_get_user(raw: Any) -> dict:
    scope = _rehydrated(raw)
    info = (scope.get("webapp.user-detail") or {}).get("userInfo") or {}
    u = _user(info.get("user"), info.get("stats"))
    if not u:
        raise ValueError("user not found in rehydration state (private, banned, or page changed)")
    return u.model_dump()


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment | None:
    if not c.get("cid"):
        return None
    return SocialComment(
        id=str(c["cid"]),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=_user({"uniqueId": (c.get("user") or {}).get("unique_id"), "nickname": (c.get("user") or {}).get("nickname"), "avatarLarger": ((c.get("user") or {}).get("avatar_thumb") or {}).get("url_list", [None])[0], "secUid": (c.get("user") or {}).get("sec_uid"), "id": (c.get("user") or {}).get("uid")}),
        content=c.get("text"),
        likes=_int(c.get("digg_count")),
        publish_time=_ts(c.get("create_time")),
        raw={"reply_count": _int(c.get("reply_comment_total")), "is_author_digged": c.get("is_author_digged"), "author_pin": c.get("author_pin")},
    )


def _comment_payload(raw: Any) -> dict:
    """/api/comment/list/ (and .../reply/) captures: the response body carries `comments` directly."""
    b = _body(raw)
    if isinstance(b.get("comments"), list):
        return b
    found = _walk(b, lambda d: isinstance(d.get("comments"), list))
    return found[0] if found else {}


def parse_get_comments(raw: Any) -> dict:
    b = _comment_payload(raw)
    items = []
    for c in b.get("comments") or []:
        if isinstance(c, dict) and (x := _comment(c, str(c.get("aweme_id") or ""))):
            items.append(x)
            for rc in c.get("reply_comment") or []:
                if isinstance(rc, dict) and (y := _comment(rc, str(c.get("aweme_id") or ""), parent_id=str(c["cid"]))):
                    items.append(y)
    out = _list_result(items, b.get("has_more"), _tab(raw))
    out["total"] = _int(b.get("total"))
    return out


def parse_get_replies(raw: Any) -> dict:
    b = _comment_payload(raw)
    root = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    items = [x for c in b.get("comments") or [] if isinstance(c, dict) and (x := _comment(c, str(c.get("aweme_id") or ""), parent_id=root or str(c.get("reply_id") or "")))]
    out = _list_result(items, bool(b.get("has_more")) and bool(items), _tab(raw))
    if out.get("cursor") and isinstance(raw, dict) and raw.get("_snippet"):
        out["cursor"] = encode_cursor({"tab": _tab(raw), "snippet": raw["_snippet"], "page": raw.get("_page") or 1})
    return out
