"""Raw 小红书 page payloads -> unified models.

Two shapes appear: API responses captured from the page (snake_case, e.g. search/notes) and
server-rendered state read from window.__INITIAL_STATE__ (camelCase). Helpers accept both.
List results return {"items", "cursor", "total"}; the cursor carries the tab id the page
was left open in (`_tab`) so the next call can scroll it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "xiaohongshu"
SITE = "https://www.xiaohongshu.com"


# ---- helpers ------------------------------------------------------------------


def _g(d: Any, *keys: str, default: Any = None) -> Any:
    """First present key among snake_case / camelCase variants."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    s = str(v).replace(",", "")
    try:
        return int(s)
    except ValueError:
        try:
            if s.endswith(("万", "w")):
                return int(float(s[:-1]) * 10000)
        except ValueError:
            pass
        return None


def _ts(v: Any) -> str | None:
    n = _int(v)
    if not n:
        return None
    if n > 10**12:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")


def _user(u: Any) -> SocialUser | None:
    if not isinstance(u, dict):
        return None
    uid = _g(u, "user_id", "userId", "id")
    if not uid:
        return None
    token = _g(u, "xsec_token", "xsecToken")
    return SocialUser(
        id=str(uid),
        platform=PLATFORM,
        name=_g(u, "nickname", "nick_name", "nickName", "name"),
        avatar_url=_g(u, "avatar", "image", "images"),
        url=f"{SITE}/user/profile/{uid}",
        raw={"xsec_token": token} if token else None,
    )


def _note_url(note_id: str, token: str | None) -> str:
    return f"{SITE}/explore/{note_id}" + (f"?xsec_token={token}&xsec_source=pc_search" if token else "")


def _note_type(v: Any) -> str:
    return "video" if str(v) == "video" else "image"


def _card_post(item: dict) -> SocialPost | None:
    """A list/search/feed card: {id, xsec_token, note_card: {...}}."""
    card = _g(item, "note_card", "noteCard", default={})
    note_id = _g(item, "id", "note_id", "noteId")
    if not note_id or not isinstance(card, dict):
        return None
    token = _g(item, "xsec_token", "xsecToken")
    inter = _g(card, "interact_info", "interactInfo", default={}) or {}
    cover = _g(card, "cover", default={}) or {}
    images = _g(card, "image_list", "imageList", default=[]) or []
    media = [
        MediaItem(type="image", url=_g(im, "url_default", "urlDefault", "url") or "", width=_g(im, "width"), height=_g(im, "height"))
        for im in images
        if isinstance(im, dict) and _g(im, "url_default", "urlDefault", "url")
    ]
    return SocialPost(
        id=str(note_id),
        platform=PLATFORM,
        type=_note_type(_g(card, "type")),
        title=_g(card, "display_title", "displayTitle", "title"),
        author=_user(_g(card, "user")),
        url=_note_url(str(note_id), token),
        cover_url=_g(cover, "url_default", "urlDefault", "url", "url_pre", "urlPre"),
        media=media,
        metrics=Metrics(
            likes=_int(_g(inter, "liked_count", "likedCount")),
            comments=_int(_g(inter, "comment_count", "commentCount")),
            shares=_int(_g(inter, "shared_count", "sharedCount")),
            collects=_int(_g(inter, "collected_count", "collectedCount")),
        ),
        publish_time=_ts(_g(card, "time")),
        raw={"xsec_token": token, "corner_tag": _g(card, "corner_tag_info", "cornerTagInfo")},
    )


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _list_result(items: list, has_more: bool | None, tab: int | None, total: int | None = None) -> dict:
    cursor = encode_cursor({"tab": tab}) if (has_more is not False and tab) else None
    return {"items": [p.model_dump() for p in items], "cursor": cursor, "total": total}


def _ended(raw: Any) -> bool:
    """The page scrolled and nothing more arrived: the list is exhausted."""
    return isinstance(raw, dict) and raw.get("end") is True


def _capture_body(raw: Any) -> dict:
    """navigate/wait_capture payloads are Capture objects: the API JSON is under `body`."""
    if _ended(raw):
        return {"data": {"items": [], "comments": [], "notes": [], "has_more": False}}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    if isinstance(raw, dict):
        return raw
    raise ValueError("unexpected payload shape")


# ---- search -------------------------------------------------------------------


def parse_search_posts(raw: Any) -> dict:
    body = _capture_body(raw)
    if body.get("success") is False or body.get("code") not in (None, 0):
        raise ValueError(f"search failed: code={body.get('code')} msg={body.get('msg')}")
    d = body.get("data") or {}
    posts = [p for it in d.get("items") or [] if _g(it, "model_type", "modelType") in (None, "note") and (p := _card_post(it))]
    return _list_result(posts, d.get("has_more"), _tab(raw))


def parse_search_users(raw: Any) -> dict:
    """search/usersearch (fired by clicking the 用户 tab): data.users[] {id, name, image, fans, note_count,
    sub_title, xsec_token, red_id, red_official_verified}, data.has_more."""
    body = _capture_body(raw)
    d = body.get("data") or {}
    items: list[SocialUser] = []
    for u in d.get("users") or []:
        if not isinstance(u, dict) or not u.get("id"):
            continue
        token = u.get("xsec_token")
        items.append(
            SocialUser(
                id=str(u["id"]),
                platform=PLATFORM,
                name=u.get("name"),
                avatar_url=u.get("image"),
                url=f"{SITE}/user/profile/{u['id']}" + (f"?xsec_token={token}&xsec_source=pc_search" if token else ""),
                bio=u.get("sub_title"),
                metrics=UserMetrics(followers=_int(u.get("fans")), posts=_int(u.get("note_count"))),
                raw={"xsec_token": token, "red_id": u.get("red_id"), "official_verified": u.get("red_official_verified"), "verify_type": u.get("red_official_verify_type")},
            )
        )
    return _list_result(items, d.get("has_more"), _tab(raw))


# ---- feed -------------------------------------------------------------------------


def parse_get_feed(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    if isinstance(raw, dict) and raw.get("ssr"):
        items = raw.get("feeds") or []
        posts = [p for it in items if isinstance(it, dict) and not it.get("ignore") and (p := _card_post(it))]
        return _list_result(posts, True, _tab(raw))
    body = _capture_body(raw)
    d = body.get("data") or {}
    posts = [p for it in d.get("items") or [] if (p := _card_post(it))]
    return _list_result(posts, True, _tab(raw))


# ---- note detail (SSR: __INITIAL_STATE__.note.noteDetailMap[id]) -----------------------


def parse_get_post(raw: Any) -> dict:
    if not isinstance(raw, dict) or "detail" not in raw:
        raise ValueError("expected {note_id, detail}")
    detail = raw["detail"] or {}
    note = detail.get("note") or {}
    if not note:
        raise ValueError("note detail missing (deleted, private, or xsec_token invalid)")
    note_id = str(note.get("noteId") or raw.get("note_id"))
    inter = note.get("interactInfo") or {}
    images = note.get("imageList") or []
    video = note.get("video") or {}
    media: list[MediaItem] = []
    if note.get("type") == "video" and video:
        streams = (video.get("media") or {}).get("stream") or {}
        best = None
        for kind in ("h264", "h265", "av1"):
            for st in streams.get(kind) or []:
                if best is None or (st.get("width") or 0) > (best.get("width") or 0):
                    best = st
        if best and best.get("masterUrl"):
            media.append(
                MediaItem(
                    type="video",
                    url=best["masterUrl"],
                    width=best.get("width"),
                    height=best.get("height"),
                    duration=(best.get("duration") or 0) / 1000 if best.get("duration") else None,
                    headers={"Referer": SITE + "/"},
                    extra={"backup_urls": best.get("backupUrls") or [], "quality": best.get("qualityType")},
                )
            )
    for im in images:
        url = _g(im, "urlDefault", "url_default", "url")
        if url:
            media.append(MediaItem(type="image", url=url, width=im.get("width"), height=im.get("height"), extra={"url_pre": im.get("urlPre")}))
    tags = [t.get("name") for t in note.get("tagList") or [] if isinstance(t, dict) and t.get("name")]
    token = note.get("xsecToken")
    first_image = next((m.url for m in media if m.type == "image"), None)
    return SocialPost(
        id=note_id,
        platform=PLATFORM,
        type=_note_type(note.get("type")),
        title=note.get("title"),
        content=note.get("desc"),
        author=_user(note.get("user")),
        url=_note_url(note_id, token),
        cover_url=first_image,
        media=media,
        metrics=Metrics(
            likes=_int(inter.get("likedCount")),
            comments=_int(inter.get("commentCount")),
            shares=_int(inter.get("shareCount")),
            collects=_int(inter.get("collectedCount")),
        ),
        publish_time=_ts(note.get("time")),
        tags=tags,
        raw={"xsec_token": token, "ip_location": note.get("ipLocation"), "last_update": _ts(note.get("lastUpdateTime")), "at_users": note.get("atUserList")},
    ).model_dump()


# ---- comments (API: comment/page) ----------------------------------------------------------


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment:
    return SocialComment(
        id=str(c.get("id")),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=_user(c.get("user_info") or {}),
        content=c.get("content"),
        likes=_int(c.get("like_count")),
        publish_time=_ts(c.get("create_time")),
        raw={"ip_location": c.get("ip_location"), "sub_comment_count": _int(c.get("sub_comment_count")), "sub_comment_has_more": c.get("sub_comment_has_more")},
    )


def parse_get_comments(raw: Any) -> dict:
    body = _capture_body(raw)
    d = body.get("data") or {}
    post_id = ""
    if isinstance(raw, dict) and "note_id=" in str(raw.get("url", "")):
        post_id = str(raw["url"]).split("note_id=")[1].split("&")[0]
    if not post_id:
        post_id = str(next((c.get("note_id") for c in d.get("comments") or [] if c.get("note_id")), ""))
    items: list[SocialComment] = []
    for c in d.get("comments") or []:
        items.append(_comment(c, post_id))
        for sc in c.get("sub_comments") or []:
            items.append(_comment(sc, post_id, parent_id=str(c.get("id"))))
    return _list_result(items, d.get("has_more"), _tab(raw))


# ---- user (SSR: __INITIAL_STATE__.user.userPageData) --------------------------------------


def parse_get_user(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("user"), dict):
        raise ValueError("expected {user}")
    u = raw["user"]
    basic = u.get("basicInfo") or {}
    counts: dict[str, int | None] = {}
    for it in u.get("interactions") or []:
        if isinstance(it, dict) and it.get("type"):
            counts[it["type"]] = _int(it.get("count"))
    href = str(raw.get("href") or "")
    uid = href.split("/user/profile/")[1].split("?")[0] if "/user/profile/" in href else str(basic.get("redId"))
    return SocialUser(
        id=str(uid),
        platform=PLATFORM,
        name=basic.get("nickname"),
        avatar_url=basic.get("imageb") or basic.get("images"),
        url=f"{SITE}/user/profile/{uid}",
        bio=basic.get("desc"),
        metrics=UserMetrics(followers=counts.get("fans"), following=counts.get("follows"), posts=None),
        raw={
            "red_id": basic.get("redId"),
            "gender": basic.get("gender"),
            "ip_location": basic.get("ipLocation"),
            "interactions": counts,
            "tags": [t.get("name") for t in u.get("tags") or [] if isinstance(t, dict) and t.get("name")],
        },
    ).model_dump()


# ---- user notes (SSR list of pages, then API user_posted) ---------------------------------


def _api_note_card(n: dict) -> SocialPost | None:
    """user_posted items are flat: {note_id, xsec_token, display_title, type, user, interact_info, cover, time}."""
    note_id = n.get("note_id")
    if not note_id:
        return None
    return _card_post({"id": note_id, "xsec_token": n.get("xsec_token"), "note_card": n})


def parse_get_user_posts(raw: Any) -> dict:
    if isinstance(raw, dict) and raw.get("ssr"):
        pages = raw.get("notes") or []
        flat = [it for page in pages for it in (page if isinstance(page, list) else [])]
        posts = [p for it in flat if isinstance(it, dict) and (p := _card_post(it))]
        queries = raw.get("queries") or []
        has_more = bool(queries[-1].get("hasMore")) if queries and isinstance(queries[-1], dict) else True
        return _list_result(posts, has_more, _tab(raw))
    body = _capture_body(raw)
    d = body.get("data") or {}
    posts = [p for n in d.get("notes") or [] if isinstance(n, dict) and (p := _api_note_card(n))]
    return _list_result(posts, d.get("has_more"), _tab(raw))


def parse_get_replies(raw: Any) -> dict:
    """/comment/sub/page: data.comments[] under root_comment_id, has_more + cursor."""
    body = _capture_body(raw)
    d = body.get("data") or {}
    url = str(raw.get("url", "")) if isinstance(raw, dict) else ""
    post_id = url.split("note_id=")[1].split("&")[0] if "note_id=" in url else ""
    root = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    if not root and "root_comment_id=" in url:
        root = url.split("root_comment_id=")[1].split("&")[0]
    items = [_comment(c, post_id or str(c.get("note_id") or ""), parent_id=root) for c in d.get("comments") or [] if isinstance(c, dict)]
    out = _list_result(items, d.get("has_more"), _tab(raw))
    if out.get("cursor") and isinstance(raw, dict) and raw.get("_snippet"):
        out["cursor"] = encode_cursor({"tab": _tab(raw), "snippet": raw["_snippet"], "page": raw.get("_page") or 1})
    return out


def parse_get_trending(raw: Any) -> dict:
    """Search-box suggestions (search/trending/query): data.queries[] {title, desc, type}. Personalised
    "猜你想搜", not a public hot list: the web site has none."""
    body = _capture_body(raw)
    d = body.get("data") or {}
    words = d.get("queries") or d.get("items") or d.get("hot_list") or []
    items = []
    for i, w in enumerate(words):
        if not isinstance(w, dict):
            continue
        title = w.get("title") or w.get("name") or w.get("word")
        if not title:
            continue
        items.append({
            "rank": _int(w.get("rank")) or i + 1,
            "type": "topic",
            "platform": PLATFORM,
            "title": title,
            "url": f"{SITE}/search_result?keyword={title}&source=web_search_result_notes",
            "heat": _int(w.get("score") or w.get("hot_value")),
            "description": w.get("desc") if w.get("desc") != title else None,
            "category": None,  # `type` is an internal routing tag like "firstEnterOther#q2q..."
            "raw": {k: v for k, v in w.items() if k not in ("title", "name", "word")},
        })
    return {"items": items, "cursor": None, "total": len(items) or None, "kind": "topics"}

