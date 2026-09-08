"""Raw 抖音 page payloads -> unified models.

Payloads are Capture objects (API JSON under `body`) or, for detail pages, the SSR
`_ROUTER_DATA.loaderData` global. List results return {"items", "cursor", "total"}; the
cursor carries the tab id (`_tab`) so the next call can scroll the same tab.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "douyin"
SITE = "https://www.douyin.com"
REFERER = {"Referer": SITE + "/"}


# ---- helpers ------------------------------------------------------------------


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> str | None:
    n = _int(v)
    if not n:
        return None
    if n > 10**12:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")


def _first_url(img: Any) -> str | None:
    if isinstance(img, dict):
        urls = img.get("url_list") or []
        return urls[0] if urls else None
    return None


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _ended(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("end") is True


def _body(raw: Any) -> dict:
    if _ended(raw):
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    if isinstance(raw, dict):
        return raw
    raise ValueError("unexpected payload shape")


def _list_result(items: list, has_more: Any, tab: int | None, total: int | None = None) -> dict:
    more = bool(has_more) if has_more is not None else True
    cursor = encode_cursor({"tab": tab}) if (more and tab) else None
    return {"items": [p.model_dump() for p in items], "cursor": cursor, "total": total}


def _user(a: Any, full: bool = False) -> SocialUser | None:
    if not isinstance(a, dict):
        return None
    sec = a.get("sec_uid")
    uid = a.get("uid") or a.get("user_id")
    if not (sec or uid):
        return None
    ident = sec or str(uid)
    return SocialUser(
        id=str(ident),
        platform=PLATFORM,
        name=a.get("nickname"),
        avatar_url=_first_url(a.get("avatar_larger") or a.get("avatar_medium") or a.get("avatar_thumb")),
        url=f"{SITE}/user/{sec}" if sec else None,
        bio=a.get("signature") if full else None,
        metrics=UserMetrics(
            followers=_int(a.get("follower_count")),
            following=_int(a.get("following_count")),
            posts=_int(a.get("aweme_count")),
        ),
        raw={
            "uid": uid,
            "unique_id": a.get("unique_id"),
            "total_favorited": _int(a.get("total_favorited")),
            "custom_verify": a.get("custom_verify") or None,
            "ip_location": a.get("ip_location"),
        },
    )


def _post(aw: dict) -> SocialPost | None:
    aweme_id = aw.get("aweme_id")
    if not aweme_id:
        return None
    video = aw.get("video") or {}
    stats = aw.get("statistics") or {}
    media: list[MediaItem] = []
    images = aw.get("images") or aw.get("image_list") or []
    if images:
        for im in images:
            url = _first_url(im)
            if url:
                media.append(MediaItem(type="image", url=url, width=im.get("width"), height=im.get("height"), headers=REFERER))
    play = video.get("play_addr") or {}
    play_url = _first_url(play)
    if play_url:
        media.append(
            MediaItem(
                type="video",
                url=play_url,
                width=play.get("width") or video.get("width"),
                height=play.get("height") or video.get("height"),
                duration=(video.get("duration") or 0) / 1000 if video.get("duration") else None,
                size=_int(play.get("data_size")),
                headers=REFERER,
                extra={"uri": play.get("uri"), "backup_urls": (play.get("url_list") or [])[1:], "h265": _first_url(video.get("play_addr_265"))},
            )
        )
    tags = [t.get("hashtag_name") for t in aw.get("text_extra") or [] if isinstance(t, dict) and t.get("hashtag_name")]
    post_type = "image" if images else "video"
    return SocialPost(
        id=str(aweme_id),
        platform=PLATFORM,
        type=post_type,
        title=None,
        content=aw.get("desc"),
        author=_user(aw.get("author")),
        url=f"{SITE}/video/{aweme_id}",
        cover_url=_first_url(video.get("origin_cover") or video.get("cover")),
        media=media,
        metrics=Metrics(
            likes=_int(stats.get("digg_count")),
            comments=_int(stats.get("comment_count")),
            shares=_int(stats.get("share_count")),
            collects=_int(stats.get("collect_count")),
            views=_int(stats.get("play_count")) or None,
        ),
        publish_time=_ts(aw.get("create_time")),
        tags=tags,
        raw={"aweme_type": aw.get("aweme_type"), "duration_ms": video.get("duration"), "music": (aw.get("music") or {}).get("title"), "group_id": aw.get("group_id")},
    )


# ---- search -------------------------------------------------------------------


def parse_search_posts(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    b = _body(raw)
    if b.get("status_code") not in (None, 0):
        raise ValueError(f"search failed: status_code={b.get('status_code')}")
    infos: list[dict] = []
    for it in b.get("data") or []:
        if isinstance(it, dict) and isinstance(it.get("aweme_info"), dict):
            infos.append(it["aweme_info"])
        for sub in it.get("aweme_list") or [] if isinstance(it, dict) else []:
            if isinstance(sub, dict) and sub.get("aweme_id"):
                infos.append(sub)
    for aw in b.get("aweme_list") or []:
        if isinstance(aw, dict) and aw.get("aweme_id"):
            infos.append(aw)
    seen: set[str] = set()
    posts = []
    for aw in infos:
        p = _post(aw)
        if p and p.id not in seen:
            seen.add(p.id)
            posts.append(p)
    return _list_result(posts, b.get("has_more"), _tab(raw))


def parse_search_users(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    b = _body(raw)
    users = []
    for entry in b.get("user_list") or []:
        u = _user(entry.get("user_info") if isinstance(entry, dict) else None, full=True)
        if u:
            users.append(u)
    return _list_result(users, b.get("has_more"), _tab(raw))


# ---- aweme lists (feed, user posts) ----------------------------------------------------


def _aweme_list(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    b = _body(raw)
    if b.get("status_code") not in (None, 0):
        raise ValueError(f"request failed: status_code={b.get('status_code')} {b.get('status_msg') or ''}")
    posts = [p for aw in b.get("aweme_list") or [] if isinstance(aw, dict) and (p := _post(aw))]
    return _list_result(posts, b.get("has_more"), _tab(raw))


parse_get_feed = _aweme_list
parse_get_user_posts = _aweme_list


# ---- placeholders until their samples are recorded --------------------------------


def _passthrough(raw: Any) -> Any:
    return raw


# ---- video detail (API: aweme/detail) ------------------------------------------------------


def parse_get_post(raw: Any) -> dict:
    b = _body(raw)
    if b.get("status_code") not in (None, 0):
        raise ValueError(f"detail request failed: status_code={b.get('status_code')}")
    aw = b.get("aweme_detail")
    if not isinstance(aw, dict):
        raise ValueError("aweme_detail missing (deleted, private, or login wall)")
    post = _post(aw)
    if post is None:
        raise ValueError("aweme_detail has no aweme_id")
    return post.model_dump()


# ---- user profile (streamed page data, camelCase) ------------------------------------------


def parse_get_user(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("user"), dict):
        raise ValueError("expected {user}")
    wrapper = raw["user"]
    u = wrapper.get("user") if isinstance(wrapper.get("user"), dict) else wrapper
    sec = u.get("secUid") or u.get("sec_uid")
    if not sec:
        raise ValueError("profile has no secUid")
    return SocialUser(
        id=str(sec),
        platform=PLATFORM,
        name=u.get("nickname"),
        avatar_url=u.get("avatar300Url") or u.get("avatarUrl"),
        url=f"{SITE}/user/{sec}",
        bio=u.get("desc"),
        metrics=UserMetrics(
            followers=_int(u.get("followerCount")),
            following=_int(u.get("followingCount")),
            posts=_int(u.get("awemeCount")),
        ),
        raw={
            "uid": u.get("uid"),
            "unique_id": u.get("uniqueId"),
            "total_favorited": _int(u.get("totalFavorited")),
            "favoriting_count": _int(u.get("favoritingCount")),
            "ip_location": u.get("ipLocation"),
            "city": u.get("city"),
            "custom_verify": u.get("customVerify") or None,
            "enterprise_verify_reason": u.get("enterpriseVerifyReason") or None,
            "gender": u.get("gender"),
        },
    ).model_dump()


# ---- comments (API: comment/list) ---------------------------------------------------------


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment:
    return SocialComment(
        id=str(c.get("cid")),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=_user(c.get("user")),
        content=c.get("text"),
        likes=_int(c.get("digg_count")),
        publish_time=_ts(c.get("create_time")),
        raw={"ip_label": c.get("ip_label"), "reply_total": _int(c.get("reply_comment_total")), "is_hot": c.get("is_hot")},
    )


def parse_get_comments(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    b = _body(raw)
    if b.get("status_code") not in (None, 0):
        raise ValueError(f"comment request failed: status_code={b.get('status_code')}")
    items: list[SocialComment] = []
    for c in b.get("comments") or []:
        if not isinstance(c, dict):
            continue
        post_id = str(c.get("aweme_id") or "")
        items.append(_comment(c, post_id))
        for rc in c.get("reply_comment") or []:
            if isinstance(rc, dict):
                items.append(_comment(rc, post_id, parent_id=str(c.get("cid"))))
    return _list_result(items, b.get("has_more"), _tab(raw), total=_int(b.get("total")))


def parse_get_replies(raw: Any) -> dict:
    """/comment/list/reply/: comments[] under one root; parent is the root cid (also `reply_id`)."""
    if _ended(raw):
        return _list_result([], False, None)
    b = _body(raw)
    if b.get("status_code") not in (None, 0):
        raise ValueError(f"reply request failed: status_code={b.get('status_code')}")
    root = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    items = []
    for c in b.get("comments") or []:
        if isinstance(c, dict):
            items.append(_comment(c, str(c.get("aweme_id") or ""), parent_id=root or str(c.get("reply_id") or "")))
    out = _list_result(items, bool(b.get("has_more")) and bool(items), _tab(raw), total=_int(b.get("total")))
    if out.get("cursor") and isinstance(raw, dict) and raw.get("_snippet"):
        out["cursor"] = encode_cursor({"tab": _tab(raw), "snippet": raw["_snippet"], "page": raw.get("_page") or 1})
    return out


def parse_get_trending(raw: Any) -> dict:
    """/hot/search/list/: data.word_list[] {word, hot_value, position, label, sentence_id}."""
    b = _body(raw)
    words = (b.get("data") or {}).get("word_list") or []
    items = []
    for i, w in enumerate(words):
        if not isinstance(w, dict) or not w.get("word"):
            continue
        items.append({
            "rank": _int(w.get("position")) or i + 1,
            "type": "topic",
            "platform": PLATFORM,
            "title": w["word"],
            "url": f"{SITE}/search/{w['word']}?type=general",
            "heat": _int(w.get("hot_value")),
            "description": None,
            "category": {1: "新", 3: "热", 4: "独家", 5: "首发", 8: "爆"}.get(_int(w.get("label")) or 0),
            "raw": {"sentence_id": w.get("sentence_id"), "label": w.get("label"), "event_time": w.get("event_time"), "video_count": w.get("video_count")},
        })
    return {"items": items, "cursor": None, "total": len(items) or None, "kind": "topics"}

