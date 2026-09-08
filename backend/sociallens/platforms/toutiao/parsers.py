"""Raw 今日头条 payloads -> unified models.

Sources (all recorded 2026-09-08, see docs/platforms/toutiao.md):
- /api/pc/list/feed (home) and /api/pc/list/user/feed (profile): {has_more, data[]} feed cells;
  cells without group_id (ads, cards) are skipped.
- /article/v4/tab_comments/: {data[{comment{...}}], has_more, offset, total_number}.
- /2/comment/v4/reply_list/: {data{data[...], has_more, offset, total_count}}.
- /hot-event/hot-board/: {data[{ClusterId, Title, HotValue, Url, Image{url}, Label}]}.
- Article / profile pages: <script id="RENDER_DATA"> URI-encoded JSON; the page hands over the raw text.
- Search (so.toutiao.com): server-rendered .result-content cards (page 1, as html[]) and JSON pages
  whose `dom` holds the same card markup.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "toutiao"
SITE = "https://www.toutiao.com"
_TAG_RE = re.compile(r"<[^>]+>")


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


def _text(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    return _html.unescape(_TAG_RE.sub("", s)).replace("\xa0", " ").strip() or None


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _body(raw: Any) -> dict:
    if isinstance(raw, dict) and raw.get("end") is True:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    return raw if isinstance(raw, dict) else {}


def _list_result(items: list, has_more: Any, tab: int | None, total: int | None = None, extra: dict | None = None) -> dict:
    cursor = encode_cursor({"tab": tab, **(extra or {})}) if (has_more and tab and items) else None
    return {"items": [i.model_dump() for i in items], "cursor": cursor, "total": total}


def _ssr(raw: Any) -> dict:
    """RENDER_DATA text (URI-encoded JSON) -> {data, query}; older payloads may carry `data` already decoded."""
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict) and not isinstance(raw.get("text"), str):
        return raw["data"]
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):
        try:
            return json.loads(unquote(raw["text"]))
        except ValueError:
            return {}
    return {}


def _url_of(uri: Any) -> str | None:
    if isinstance(uri, dict):
        u = uri.get("url") or ((uri.get("url_list") or [{}])[0].get("url") if isinstance(uri.get("url_list"), list) else None)
        return str(u) if u else None
    return str(uri) if isinstance(uri, str) and uri.startswith("http") else None


def _author(info: Any) -> SocialUser | None:
    if not isinstance(info, dict) or not (info.get("user_id") or info.get("name")):
        return None
    uid = str(info.get("user_id") or "")
    auth = info.get("user_auth_info")
    if isinstance(auth, str) and auth.startswith("{"):
        try:
            auth = json.loads(auth)
        except ValueError:
            pass
    return SocialUser(
        id=uid,
        platform=PLATFORM,
        name=info.get("name"),
        avatar_url=info.get("avatar_url"),
        url=f"{SITE}/c/user/token/{uid}/" if uid.startswith("MS4w") else None,
        bio=info.get("description") or None,
        metrics=UserMetrics(followers=_int(info.get("follow_count") or info.get("fans_count")), posts=None),
        raw={"verified": info.get("user_verified"), "auth": (auth.get("auth_info") if isinstance(auth, dict) else auth) or None, "media_id": info.get("media_id")},
    )


def _post(it: dict) -> SocialPost | None:
    gid = str(it.get("group_id") or it.get("item_id") or it.get("id") or "")
    if not gid.isdigit():
        return None
    action = it.get("action") if isinstance(it.get("action"), dict) else {}
    video = bool(it.get("has_video")) or bool(it.get("video_duration")) or bool(it.get("video_detail_info")) or it.get("cell_type") == 49
    cover = _url_of(it.get("middle_image")) or _url_of((it.get("large_image_list") or [None])[0]) or _url_of(((it.get("video_detail_info") or {}).get("detail_video_large_image")))
    media = [MediaItem(type="image", url=u) for im in (it.get("image_list") or []) if (u := _url_of(im))]
    author = _author(it.get("user_info") or it.get("media_info") or ({"name": it.get("media_name")} if it.get("media_name") else None))
    kw = it.get("keywords")
    return SocialPost(
        id=gid,
        platform=PLATFORM,
        type="video" if video else "article",
        title=it.get("title") or None,
        content=it.get("Abstract") or it.get("abstract") or None,
        author=author,
        url=f"{SITE}/{'video' if video else 'article'}/{gid}/",
        cover_url=cover,
        media=media,
        metrics=Metrics(
            likes=_int(it.get("digg_count")) or _int(action.get("digg_count")) or _int(it.get("like_count")),
            comments=_int(it.get("comment_count")) or _int(action.get("comment_count")),
            shares=_int(it.get("share_count")) or _int(action.get("share_count")),
            collects=_int(it.get("repin_count")) or _int(action.get("repin_count")),
            views=_int(it.get("read_count")) or _int(action.get("read_count")) or _int(action.get("play_count")),
        ),
        publish_time=_ts(it.get("publish_time") or it.get("behot_time")),
        tags=[k for k in str(kw).split(",") if k] if isinstance(kw, str) else [],
        raw={"article_url": it.get("article_url") or it.get("url"), "source": it.get("source") or it.get("media_name"), "duration": _int(it.get("video_duration")), "cell_type": it.get("cell_type"), "group_source": it.get("group_source")},
    )


def _feed(raw: Any) -> dict:
    b = _body(raw)
    items = [p for it in b.get("data") or [] if isinstance(it, dict) and (p := _post(it))]
    return _list_result(items, b.get("has_more"), _tab(raw))


parse_get_feed = _feed
parse_get_user_posts = _feed


def parse_get_trending(raw: Any) -> dict:
    b = _body(raw)
    items = []
    for i, it in enumerate(b.get("data") or []):
        if not isinstance(it, dict) or not it.get("Title"):
            continue
        items.append({"rank": i + 1, "id": str(it.get("ClusterIdStr") or it.get("ClusterId") or ""), "title": it["Title"], "url": it.get("Url"), "heat": _int(it.get("HotValue")), "cover_url": _url_of(it.get("Image")), "label": it.get("Label") or it.get("LabelDesc") or None})
    return {"items": items, "cursor": None, "total": len(items) or None, "kind": "topics"}


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment | None:
    cid = str(c.get("id_str") or c.get("id") or "")
    if not cid:
        return None
    u = c.get("user") if isinstance(c.get("user"), dict) else None
    author = SocialUser(
        id=str((u or {}).get("user_id") or c.get("user_id") or ""),
        platform=PLATFORM,
        name=(u or {}).get("name") or c.get("user_name"),
        avatar_url=(u or {}).get("avatar_url") or c.get("user_profile_image_url"),
        raw={"auth": c.get("user_auth_info") or (u or {}).get("user_auth_info") or None, "is_author": bool(c.get("is_pgc_author"))},
    )
    return SocialComment(
        id=cid,
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=author,
        content=c.get("text") or None,
        likes=_int(c.get("digg_count")),
        publish_time=_ts(c.get("create_time")),
        raw={"reply_count": _int(c.get("reply_count")), "location": (c.get("publish_loc_info") or None), "images": [u for im in c.get("large_image_list") or [] if (u := _url_of(im))]},
    )


def _post_id_from(raw: Any) -> str:
    if isinstance(raw, dict) and raw.get("_post_id"):
        return str(raw["_post_id"])
    url = str(raw.get("url") or "") if isinstance(raw, dict) else ""
    q = parse_qs(urlparse(url).query)
    return str((q.get("group_id") or q.get("item_id") or [""])[0])


def parse_get_comments(raw: Any) -> dict:
    b = _body(raw)
    pid = _post_id_from(raw)
    items = [c for it in b.get("data") or [] if isinstance(it, dict) and isinstance(it.get("comment"), dict) and (c := _comment(it["comment"], pid))]
    return _list_result(items, b.get("has_more"), _tab(raw), total=_int(b.get("total_number")))


def parse_get_replies(raw: Any) -> dict:
    b = _body(raw)
    d = b.get("data") if isinstance(b.get("data"), dict) else b
    parent = str((raw.get("_comment_id") if isinstance(raw, dict) else None) or d.get("id_str") or d.get("id") or "")
    pid = _post_id_from(raw)
    items = [c for it in d.get("data") or [] if isinstance(it, dict) and (c := _comment(it, pid, parent_id=parent or None))]
    page = int((raw.get("_page") if isinstance(raw, dict) else 0) or 0)
    return _list_result(items, d.get("has_more"), _tab(raw), total=_int(d.get("total_count")), extra={"page": page} if page else None)


def _video_post(data: dict) -> SocialPost:
    """/video/{id}/ pages: RENDER_DATA.data.initialVideo {title, coverUrl, publishTime, userInfo, playCount,
    diggCount, commentCount, repinCount, duration, videoPlayInfo.video_list[{main_url, backup_url, video_meta{definition,vwidth,vheight,size}}]}."""
    v = data.get("initialVideo") or {}
    gid = str(v.get("group_id") or v.get("groupId") or data.get("groupId") or "")
    media: list[MediaItem] = []
    for it in ((v.get("videoPlayInfo") or {}).get("video_list") or []):
        if not isinstance(it, dict) or not it.get("main_url"):
            continue
        meta = it.get("video_meta") if isinstance(it.get("video_meta"), dict) else {}
        media.append(MediaItem(type="video", url=str(it["main_url"]), width=_int(meta.get("vwidth")), height=_int(meta.get("vheight")), size=_int(meta.get("size")), duration=float(v["duration"]) if _int(v.get("duration")) else None, extra={"definition": meta.get("definition"), "backup_urls": [it["backup_url"]] if it.get("backup_url") else [], "cover_url": v.get("coverUrl")}))
    media.sort(key=lambda m: m.width or 0, reverse=True)  # best quality first: the download takes media[0]
    ui = v.get("userInfo") or {}
    return SocialPost(
        id=gid,
        platform=PLATFORM,
        type="video",
        title=v.get("title"),
        content=v.get("abstract") or None,
        author=_author({"user_id": ui.get("userId"), "name": ui.get("name"), "avatar_url": ui.get("avatarUrl"), "user_auth_info": ui.get("userAuthInfo"), "user_verified": ui.get("userVerified"), "media_id": v.get("mediaId")}),
        url=f"{SITE}/video/{gid}/",
        cover_url=v.get("coverUrl") or None,
        media=media[:1] + media[1:],
        metrics=Metrics(likes=_int(v.get("diggCount")), comments=_int(v.get("commentCount")), collects=_int(v.get("repinCount")), views=_int(v.get("playCount"))),
        publish_time=_ts(v.get("publishTime")),
        tags=[k for k in str((data.get("seoTDK") or {}).get("keywords") or "").split(",") if k][:20],
        raw={"duration": _int(v.get("duration")), "video_id": v.get("videoId"), "definitions": [m.extra.get("definition") for m in media], "url_expire": (v.get("videoPlayInfo") or {}).get("url_expire")},
    )


def parse_get_post(raw: Any) -> dict:
    data = (_ssr(raw) or {}).get("data") or {}
    if isinstance(data.get("initialVideo"), dict) and (data["initialVideo"].get("title") or data["initialVideo"].get("group_id")):
        return _video_post(data).model_dump()
    if not data.get("title") and not data.get("groupId"):
        raise ValueError("article not found in RENDER_DATA (deleted, a video page, or page changed)")
    gid = str(data.get("groupId") or data.get("itemId") or "")
    content_html = data.get("content") if isinstance(data.get("content"), str) else None
    images = [MediaItem(type="image", url=u) for im in data.get("imageList") or [] if (u := _url_of(im))]
    if not images and content_html:
        images = [MediaItem(type="image", url=m) for m in dict.fromkeys(re.findall(r'<img[^>]+src="([^"]+)"', content_html))]
    mi = data.get("mediaInfo") or {}
    author = _author({"user_id": mi.get("userId"), "name": mi.get("name"), "avatar_url": mi.get("avatarUrl"), "description": mi.get("description"), "user_verified": mi.get("userVerified"), "user_auth_info": mi.get("userAuthInfo")}) if mi else None
    seo = data.get("seoTDK") or {}
    p = SocialPost(
        id=gid,
        platform=PLATFORM,
        type="video" if data.get("articleType") == "video" or data.get("videoData") else "article",
        title=data.get("title"),
        content=_text(content_html) or data.get("abstract"),
        author=author,
        url=f"{SITE}{data.get('pathname') or f'/article/{gid}/'}",
        cover_url=data.get("cover") or None,
        media=images,
        metrics=Metrics(likes=_int((data.get("likeData") or {}).get("count")), comments=_int(data.get("commentCount") or data.get("comment_count"))),
        publish_time=_ts(seo.get("publishTimestamp")) or data.get("publishTime"),
        tags=[k for k in str(seo.get("keywords") or "").split(",") if k][:20],
        raw={"abstract": data.get("abstract"), "source": data.get("source"), "content_html": content_html, "is_original": data.get("isOriginal"), "article_type": data.get("articleType")},
    )
    return p.model_dump()


def parse_get_user(raw: Any) -> dict:
    data = (_ssr(raw) or {}).get("data") or {}
    info = data.get("profileUserInfo") or {}
    if not info.get("userId"):
        raise ValueError("profile not found in RENDER_DATA (page changed?)")
    u = _author({"user_id": info.get("userId"), "name": info.get("name") or info.get("screenName"), "avatar_url": info.get("avatarUrl"), "description": info.get("description"), "user_verified": info.get("userVerified"), "user_auth_info": info.get("userAuthInfo"), "media_id": info.get("mediaId")})
    assert u is not None
    u.raw = {**(u.raw or {}), "ip_location": info.get("ipLocation"), "is_pgc": info.get("isPgc"), "followers": _int(info.get("followersCount") or info.get("fansCount"))}
    if u.raw.get("followers"):
        u.metrics.followers = u.raw["followers"]
    return u.model_dump()


# ---- search (server-rendered cards) --------------------------------------------------------------

_CARD_SPLIT = re.compile(r'(?=<div class="result-content")')
_TIME_RE = re.compile(r"(\d+\s*(?:秒|分钟|小时|天)前|昨天\s*\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}(?:\s*\d{1,2}:\d{2})?|\d{1,2}月\d{1,2}日|\d{2}-\d{2})")


def _attr_json(card: str, name: str) -> dict:
    m = re.search(rf'{name}="([^"]*)"', card)
    if not m:
        return {}
    try:
        v = json.loads(_html.unescape(m.group(1)))
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _card(card: str) -> SocialPost | None:
    cr = _attr_json(card, "cr-params")
    log = _attr_json(card, "data-log-extra")
    gid = str(log.get("group_id") or cr.get("gid") or "")
    if not gid.isdigit() or len(gid) < 15:  # aladdin / vertical cards (video oracles, product cards) carry short ids
        return None
    body = re.sub(r"<script.*?</script>", "", card, flags=re.S)
    pieces = [t for t in (_text(x) for x in re.split(r"<[^>]+>", body)) if t]
    title = _text(cr.get("title")) or (pieces[0] if pieces else None)
    when = next((m.group(1) for t in pieces if (m := _TIME_RE.fullmatch(t.strip()))), None)
    # the longest text that is not the title is the abstract; the piece before the time is usually the source
    abstract = max((t for t in pieces if t != title and len(t) > 12 and not _TIME_RE.fullmatch(t)), key=len, default=None)
    src = None
    if when and when in pieces:
        i = pieces.index(when)
        src = pieces[i - 1] if i > 0 and len(pieces[i - 1]) <= 30 and pieces[i - 1] not in (title, abstract) else None
    target = None
    for m in re.finditer(r'href="([^"]+)"', card):
        href = _html.unescape(m.group(1))
        q = parse_qs(urlparse(href).query)
        if "url" in q:
            target = q["url"][0]
            break
    cover = next((u for u in re.findall(r'<img[^>]+src="([^"]+)"', card) if u.startswith("http")), None)
    video = log.get("result_type") in ("video", "self_video", "xiaoshipin") or log.get("display_type_self") == "video"
    return SocialPost(
        id=gid,
        platform=PLATFORM,
        type="video" if video else "article",
        title=title,
        content=abstract,
        author=SocialUser(id="", platform=PLATFORM, name=src) if src else None,
        url=f"{SITE}/{'video' if video else 'article'}/{gid}/",
        cover_url=cover,
        publish_time=None,
        raw={"time_text": when, "result_type": log.get("result_type"), "target_url": target, "source": src},
    )


def parse_search_posts(raw: Any) -> dict:
    b = _body(raw)
    if isinstance(b.get("html"), list):  # page 1: card markup read from the DOM
        cards = [c for c in b["html"] if isinstance(c, str)]
        has_more = True
    else:  # later pages: JSON with the same markup in `dom`
        cards = [c for c in _CARD_SPLIT.split(str(b.get("dom") or "")) if c.startswith("<div class=\"result-content\"")]
        has_more = bool(b.get("has_more") or b.get("has_next"))
    items = [p for c in cards if (p := _card(c))]
    return _list_result(items, has_more, _tab(raw))
