"""Raw Instagram payloads -> unified models.

Sources (recorded 2026-09-08, see docs/platforms/instagram.md). Every GraphQL answer is
{"data": {<field>: ...}}; server-rendered pages carry the same shapes nested inside Relay preloader
blocks ({"require": [["ScheduledServerJS", ...]]}) which are walked for the field:
- xdt_api__v1__feed__timeline__connection / feed__user_timeline_graphql_connection: edges[].node (media)
- xdt_fbsearch__top_serp_graphql: edges[].node.items[] (media)
- xdt_api__v1__fbsearch__topsearch_connection: users[].user, hashtags[], places[]
- xdt_api__v1__media__shortcode__web_info: items[0] (media)
- xdt_api__v1__media__media_id__comments__connection and ..._child_comments__connection: edges[].node
- /api/v1/discover/web/explore_grid/: sectional_items[] with nested {media} dicts, next_max_id
- user (profile query): pk, username, full_name, biography, follower_count, following_count, media_count
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "instagram"
SITE = "https://www.instagram.com"


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


def _find_key(obj: Any, key: str, depth: int = 0) -> Any:
    """First value of `key` anywhere in a nested payload (Relay preloader blocks nest data deeply)."""
    if depth > 60:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key, depth + 1)
            if found is not None:
                return found
    return None


def _payload(raw: Any) -> Any:
    """Captured body, or the decoded server-rendered block (`text`)."""
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):
        try:
            return json.loads(raw["text"])
        except ValueError:
            return {}
    return _body(raw)


def _list_result(items: list, has_more: Any, tab: int | None, total: int | None = None) -> dict:
    return {"items": [i.model_dump() for i in items], "cursor": encode_cursor({"tab": tab}) if (has_more and tab and items) else None, "total": total}


def _user(u: Any) -> SocialUser | None:
    if not isinstance(u, dict) or not (u.get("username") or u.get("pk")):
        return None
    name = u.get("username")
    hd = u.get("hd_profile_pic_url_info") if isinstance(u.get("hd_profile_pic_url_info"), dict) else {}
    return SocialUser(
        id=str(u.get("pk") or u.get("id") or ""),
        platform=PLATFORM,
        name=name,
        avatar_url=hd.get("url") or u.get("profile_pic_url"),
        url=f"{SITE}/{name}/" if name else None,
        bio=u.get("biography") or None,
        metrics=UserMetrics(followers=_int(u.get("follower_count")), following=_int(u.get("following_count")), posts=_int(u.get("media_count"))),
        raw={"full_name": u.get("full_name"), "is_verified": u.get("is_verified"), "is_private": u.get("is_private"), "category": u.get("category"), "external_url": u.get("external_url"), "bio_links": [b.get("url") for b in u.get("bio_links") or [] if isinstance(b, dict) and b.get("url")], "total_clips": _int(u.get("total_clips_count"))},
    )


def _candidate_url(versions: Any) -> str | None:
    cands = (versions or {}).get("candidates") if isinstance(versions, dict) else versions
    if isinstance(cands, list) and cands and isinstance(cands[0], dict):
        return cands[0].get("url")
    return None


def _media_items(m: dict) -> list[MediaItem]:
    out: list[MediaItem] = []
    parts = m.get("carousel_media") if isinstance(m.get("carousel_media"), list) and m.get("carousel_media") else [m]
    for part in parts:
        if not isinstance(part, dict):
            continue
        vv = part.get("video_versions")
        if isinstance(vv, list) and vv and isinstance(vv[0], dict) and vv[0].get("url"):
            out.append(MediaItem(type="video", url=vv[0]["url"], width=_int(vv[0].get("width")), height=_int(vv[0].get("height")), extra={"cover_url": _candidate_url(part.get("image_versions2")), "has_audio": part.get("has_audio")}))
            continue
        u = _candidate_url(part.get("image_versions2")) or part.get("display_uri")
        if u:
            out.append(MediaItem(type="image", url=u, width=_int(part.get("original_width")), height=_int(part.get("original_height"))))
    return out


def _post(m: Any) -> SocialPost | None:
    if not isinstance(m, dict) or not (m.get("code") or m.get("pk")):
        return None
    code = m.get("code")
    mt = m.get("media_type")
    product = m.get("product_type")
    cap = m.get("caption") if isinstance(m.get("caption"), dict) else {}
    media = _media_items(m)
    ptype = "video" if (mt == 2 or product == "clips" or any(x.type == "video" for x in media)) else "image"
    loc = m.get("location") if isinstance(m.get("location"), dict) else {}
    return SocialPost(
        id=str(m.get("pk") or str(m.get("id") or "").split("_")[0]),
        platform=PLATFORM,
        type=ptype,
        title=None,
        content=cap.get("text") or None,
        author=_user(m.get("user") or m.get("owner")),
        url=f"{SITE}/{'reel' if product == 'clips' else 'p'}/{code}/" if code else None,
        cover_url=_candidate_url(m.get("image_versions2")) or m.get("display_uri") or None,
        media=media,
        metrics=Metrics(likes=_int(m.get("like_count")), comments=_int(m.get("comment_count")), views=_int(m.get("play_count") or m.get("view_count") or m.get("ig_play_count")), shares=_int(m.get("reshare_count"))),
        publish_time=_ts(m.get("taken_at") or cap.get("created_at")),
        tags=[],
        raw={"code": code, "media_type": mt, "product_type": product, "carousel_count": _int(m.get("carousel_media_count")), "location": loc.get("name"), "accessibility_caption": m.get("accessibility_caption"), "is_paid_partnership": m.get("is_paid_partnership"), "has_audio": m.get("has_audio")},
    )


def _connection(raw: Any, field: str) -> tuple[list[dict], dict]:
    conn = _find_key(_payload(raw), field) or {}
    edges = conn.get("edges") if isinstance(conn, dict) else None
    nodes = [e.get("node") for e in edges or [] if isinstance(e, dict) and isinstance(e.get("node"), dict)]
    return nodes, (conn.get("page_info") or {}) if isinstance(conn, dict) else {}


def parse_get_feed(raw: Any) -> dict:
    nodes, page = _connection(raw, "xdt_api__v1__feed__timeline__connection")
    items = [p for n in nodes if (p := _post(n.get("media")))]
    return _list_result(items, page.get("has_next_page", bool(nodes)), _tab(raw))


def parse_get_user_posts(raw: Any) -> dict:
    nodes, page = _connection(raw, "xdt_api__v1__feed__user_timeline_graphql_connection")
    items = [p for n in nodes if (p := _post(n))]
    return _list_result(items, page.get("has_next_page"), _tab(raw))


def parse_search_posts(raw: Any) -> dict:
    nodes, page = _connection(raw, "xdt_fbsearch__top_serp_graphql")
    items = []
    for n in nodes:
        for it in n.get("items") or []:
            if p := _post(it):
                items.append(p)
    return _list_result(items, page.get("has_next_page"), _tab(raw))


def parse_search_users(raw: Any) -> dict:
    top = _find_key(_payload(raw), "xdt_api__v1__fbsearch__topsearch_connection") or {}
    items = [u for e in top.get("users") or [] if isinstance(e, dict) and (u := _user(e.get("user")))]
    for u, e in zip(items, [e for e in top.get("users") or [] if isinstance(e, dict) and isinstance(e.get("user"), dict)]):
        u.raw = {**(u.raw or {}), "search_context": (e["user"].get("search_social_context") or None)}
    return {"items": [u.model_dump() for u in items], "cursor": None, "total": len(items) or None}


def parse_get_user(raw: Any) -> dict:
    payload = _payload(raw)
    u = (payload.get("data") or {}).get("user") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else None
    user = _user(u or _find_key(payload, "user"))
    if not user:
        raise ValueError("user not found in the profile payload (page changed?)")
    return user.model_dump()


def parse_get_post(raw: Any) -> dict:
    info = _find_key(_payload(raw), "xdt_api__v1__media__shortcode__web_info") or {}
    items = info.get("items") if isinstance(info, dict) else None
    p = _post(items[0]) if items else None
    if not p:
        raise ValueError("post not found in the page payload (removed, private, or page changed)")
    return p.model_dump()


def _comment(n: dict, post_id: str, parent_id: str | None = None) -> SocialComment | None:
    if not n.get("pk"):
        return None
    return SocialComment(
        id=str(n["pk"]),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id or (str(n["parent_comment_id"]) if n.get("parent_comment_id") else None),
        author=_user(n.get("user")),
        content=n.get("text") or None,
        likes=_int(n.get("comment_like_count")),
        publish_time=_ts(n.get("created_at")),
        raw={"reply_count": _int(n.get("child_comment_count")), "is_edited": n.get("is_edited"), "has_translation": n.get("has_translation")},
    )


def _post_id(raw: Any) -> str:
    if isinstance(raw, dict):
        if raw.get("_post_id"):
            return str(raw["_post_id"])
        href = str(raw.get("href") or "")
        for marker in ("/p/", "/reel/", "/reels/"):
            if marker in href:
                return href.split(marker, 1)[1].split("/")[0]
    return ""


def parse_get_comments(raw: Any) -> dict:
    nodes, page = _connection(raw, "xdt_api__v1__media__media_id__comments__connection")
    pid = _post_id(raw)
    items = [c for n in nodes if (c := _comment(n, pid))]
    return _list_result(items, page.get("has_next_page"), _tab(raw))


def parse_get_replies(raw: Any) -> dict:
    nodes, page = _connection(raw, "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection")
    pid = _post_id(raw)
    parent = str((raw.get("_comment_id") if isinstance(raw, dict) else "") or "")
    items = [c for n in nodes if (c := _comment(n, pid, parent_id=parent or None))]
    return _list_result(items, page.get("has_next_page"), _tab(raw))


def _walk_media(obj: Any, out: list, depth: int = 0) -> None:
    if depth > 30:
        return
    if isinstance(obj, dict):
        m = obj.get("media")
        if isinstance(m, dict) and (m.get("code") or m.get("pk")):
            out.append(m)
            return
        for v in obj.values():
            _walk_media(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk_media(v, out, depth + 1)


def parse_get_trending(raw: Any) -> dict:
    """Page 1: the server-rendered preloader block; later pages: /discover/web/explore_grid/ JSON."""
    b = _payload(raw)
    if _find_key(b, "sectional_items") is None:
        # the preloader cache keeps the REST answer as a JSON string under result.response
        resp = _find_key(b, "response")
        if isinstance(resp, str) and "sectional_items" in resp:
            try:
                b = json.loads(resp)
            except ValueError:
                pass
    medias: list[dict] = []
    _walk_media(_find_key(b, "sectional_items") or b, medias)
    if isinstance(b, dict) and "more_available" not in b:
        b = {**b, "more_available": _find_key(b, "more_available")}
    seen: set[str] = set()
    items = []
    for m in medias:
        p = _post(m)
        if p and p.id not in seen:
            seen.add(p.id)
            items.append(p)
    return _list_result(items, b.get("more_available", bool(items)), _tab(raw))
