"""Raw YouTube payloads -> unified models.

Payloads are either server-rendered globals ({"ssr": true, "data": ytInitialData, "player":
ytInitialPlayerResponse}) or captured youtubei/v1 responses (Capture objects with `body`).
Both are renderer trees; the parsers walk them looking for renderer objects by shape.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "youtube"
SITE = "https://www.youtube.com"


# ---- helpers ---------------------------------------------------------------------


def _walk(obj: Any, pred: Callable[[dict], bool], depth: int = 0, out: list | None = None) -> list[dict]:
    out = out if out is not None else []
    if depth > 60:
        return out
    if isinstance(obj, dict):
        if pred(obj):
            out.append(obj)
            return out  # do not descend into a matched renderer (avoids nested duplicates)
        for v in obj.values():
            _walk(v, pred, depth + 1, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, pred, depth + 1, out)
    return out


def _text(v: Any) -> str | None:
    """Flatten YouTube text objects: {"simpleText"} or {"runs": [{"text"}]} or {"content"}."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if isinstance(v.get("simpleText"), str):
            return v["simpleText"]
        if isinstance(v.get("content"), str):
            return v["content"]
        if isinstance(v.get("runs"), list):
            return "".join(str(r.get("text", "")) for r in v["runs"] if isinstance(r, dict))
    return None


_NUM = re.compile(r"[\d,.]+")
_UNITS = {"万": 10_000, "亿": 100_000_000, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "千": 1_000}


def _count(v: Any) -> int | None:
    """'64,347,035次观看' / '269万位订阅者' / '1.2M views' / '12345' -> int."""
    s = _text(v) if not isinstance(v, (int, float)) else v
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = _NUM.search(s.replace(",", ""))
    if not m:
        return None
    n = float(m.group(0))
    rest = s[m.end():m.end() + 2]
    for u, mult in _UNITS.items():
        if rest.startswith(u):
            n *= mult
            break
    return int(n)


_REL = [(re.compile(r"(\d+)\s*(秒|second)"), 1), (re.compile(r"(\d+)\s*(分钟|minute)"), 60), (re.compile(r"(\d+)\s*(小时|hour)"), 3600), (re.compile(r"(\d+)\s*(天|day)"), 86400), (re.compile(r"(\d+)\s*(周|week)"), 604800), (re.compile(r"(\d+)\s*(个月|month)"), 2592000), (re.compile(r"(\d+)\s*(年|year)"), 31536000)]


def _relative_time(v: Any) -> str | None:
    """'1年前' / '3 days ago' -> approximate ISO timestamp (day precision at best)."""
    s = _text(v)
    if not s:
        return None
    for rx, secs in _REL:
        m = rx.search(s)
        if m:
            return (datetime.now(timezone.utc) - timedelta(seconds=int(m.group(1)) * secs)).replace(microsecond=0).isoformat()
    return None


def _thumb(v: Any) -> str | None:
    thumbs = (v or {}).get("thumbnails") if isinstance(v, dict) else None
    if isinstance(thumbs, list) and thumbs:
        best = max((t for t in thumbs if isinstance(t, dict) and t.get("url")), key=lambda t: t.get("width") or 0, default=None)
        return best.get("url") if best else None
    return None


def _browse(obj: Any) -> tuple[str | None, str | None]:
    """(channel browseId, canonical @handle path) found anywhere in a renderer fragment."""
    ep = _walk(obj, lambda d: isinstance(d.get("browseEndpoint"), dict))
    for e in ep:
        be = e.get("browseEndpoint") or {}
        if be.get("browseId"):
            return be.get("browseId"), be.get("canonicalBaseUrl")
    return None, None


def _duration(v: Any) -> float | None:
    s = _text(v)
    if not s or ":" not in s:
        return None
    parts = [int(p) for p in s.split(":") if p.isdigit()]
    total = 0
    for p in parts:
        total = total * 60 + p
    return float(total)


def _payload(raw: Any) -> Any:
    if isinstance(raw, dict) and raw.get("end") is True:
        return {}
    if isinstance(raw, dict) and raw.get("ssr"):
        return raw.get("data")
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    return raw


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _list_result(items: list, tab: int | None, has_more: bool = True) -> dict:
    return {"items": [p.model_dump() for p in items], "cursor": encode_cursor({"tab": tab}) if (has_more and tab and items) else None, "total": None}


# ---- videos ----------------------------------------------------------------------


def _is_video(d: dict) -> bool:
    return isinstance(d.get("videoId"), str) and "title" in d and ("viewCountText" in d or "ownerText" in d or "lengthText" in d or "publishedTimeText" in d)


def _video(d: dict) -> SocialPost | None:
    vid = d.get("videoId")
    if not vid:
        return None
    owner = d.get("ownerText") or d.get("longBylineText") or d.get("shortBylineText")
    cid, handle = _browse(owner)
    author = None
    if owner and (cid or _text(owner)):
        author = SocialUser(id=str(cid or handle or _text(owner)), platform=PLATFORM, name=_text(owner), url=f"{SITE}{handle}" if handle else (f"{SITE}/channel/{cid}" if cid else None))
    return SocialPost(
        id=str(vid),
        platform=PLATFORM,
        type="video",
        title=_text(d.get("title")),
        content=_text((d.get("detailedMetadataSnippets") or [{}])[0].get("snippetText")) if d.get("detailedMetadataSnippets") else _text(d.get("descriptionSnippet")),
        author=author,
        url=f"{SITE}/watch?v={vid}",
        cover_url=_thumb(d.get("thumbnail")),
        metrics=Metrics(views=_count(d.get("viewCountText"))),
        publish_time=_relative_time(d.get("publishedTimeText")),
        raw={"duration_s": _duration(d.get("lengthText")), "published_text": _text(d.get("publishedTimeText")), "view_text": _text(d.get("viewCountText"))},
    )


def _lockup(d: dict) -> SocialPost | None:
    """2025+ grid layout: lockupViewModel {contentId, metadata.lockupMetadataViewModel{title, metadata.contentMetadataViewModel.metadataRows}, contentImage}."""
    vid = d.get("contentId")
    if not vid or d.get("contentType") not in (None, "LOCKUP_CONTENT_TYPE_VIDEO"):
        return None
    meta = (d.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    rows = ((meta.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []
    parts: list[str] = []
    for row in rows:
        for part in row.get("metadataParts") or []:
            t = _text(part.get("text"))
            if t:
                parts.append(t)
    views = next((_count(t) for t in parts if "观看" in t or "view" in t.lower()), None)
    published = next((t for t in parts if "前" in t or "ago" in t.lower()), None)
    owner = next((t for t in parts if t and not ("观看" in t or "view" in t.lower() or "前" in t or "ago" in t.lower())), None)
    cid, handle = _browse(meta)
    image = ((d.get("contentImage") or {}).get("thumbnailViewModel") or {}).get("image") or {}
    sources = image.get("sources") or []
    cover = max((x for x in sources if isinstance(x, dict) and x.get("url")), key=lambda x: x.get("width") or 0, default={}).get("url")
    author = SocialUser(id=str(cid or handle or owner), platform=PLATFORM, name=owner, url=f"{SITE}{handle}" if handle else (f"{SITE}/channel/{cid}" if cid else None)) if (owner or cid) else None
    overlays = _walk(d.get("contentImage"), lambda x: "thumbnailBadgeViewModel" in x)
    length = next((_text((o.get("thumbnailBadgeViewModel") or {}).get("text")) for o in overlays if ":" in (_text((o.get("thumbnailBadgeViewModel") or {}).get("text")) or "")), None)
    return SocialPost(
        id=str(vid),
        platform=PLATFORM,
        type="video",
        title=_text(meta.get("title")),
        author=author,
        url=f"{SITE}/watch?v={vid}",
        cover_url=cover,
        metrics=Metrics(views=views),
        publish_time=_relative_time(published),
        raw={"duration_s": _duration(length), "published_text": published, "metadata_parts": parts[:6]},
    )


def _shorts(d: dict) -> SocialPost | None:
    """shortsLockupViewModel: {entityId, overlayMetadata{primaryText, secondaryText}, onTap.innertubeCommand.reelWatchEndpoint.videoId, thumbnail}."""
    ep = _walk(d.get("onTap"), lambda x: "reelWatchEndpoint" in x)
    vid = ((ep[0].get("reelWatchEndpoint") or {}).get("videoId")) if ep else None
    if not vid:
        return None
    om = d.get("overlayMetadata") or {}
    sources = ((d.get("thumbnail") or {}).get("sources")) or []
    cover = max((x for x in sources if isinstance(x, dict) and x.get("url")), key=lambda x: x.get("width") or 0, default={}).get("url")
    return SocialPost(
        id=str(vid),
        platform=PLATFORM,
        type="video",
        title=_text(om.get("primaryText")),
        url=f"{SITE}/shorts/{vid}",
        cover_url=cover,
        metrics=Metrics(views=_count(om.get("secondaryText"))),
        raw={"shorts": True, "view_text": _text(om.get("secondaryText"))},
    )


def _videos(raw: Any) -> list[SocialPost]:
    seen: set[str] = set()
    out: list[SocialPost] = []
    payload = _payload(raw)
    candidates: list[SocialPost | None] = [_video(d) for d in _walk(payload, _is_video)]
    candidates += [_lockup(d["lockupViewModel"]) for d in _walk(payload, lambda x: isinstance(x.get("lockupViewModel"), dict))]
    candidates += [_shorts(d["shortsLockupViewModel"]) for d in _walk(payload, lambda x: isinstance(x.get("shortsLockupViewModel"), dict))]
    for p in candidates:
        if p and p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out


def _has_continuation(raw: Any) -> bool:
    return bool(_walk(_payload(raw), lambda d: "continuationCommand" in d or "continuationEndpoint" in d))


def parse_search_posts(raw: Any) -> dict:
    return _list_result(_videos(raw), _tab(raw), _has_continuation(raw))


parse_get_user_posts = parse_search_posts
parse_get_feed = parse_search_posts


# ---- channels ------------------------------------------------------------------------


def _channel(d: dict) -> SocialUser | None:
    cid = d.get("channelId")
    if not cid:
        return None
    _, handle = _browse(d.get("navigationEndpoint"))
    # YouTube swapped these two fields in recent layouts: subscriberCountText often carries the @handle.
    sub_text = _text(d.get("videoCountText")) if "订阅" in (_text(d.get("videoCountText")) or "") or "subscriber" in (_text(d.get("videoCountText")) or "").lower() else _text(d.get("subscriberCountText"))
    return SocialUser(
        id=str(cid),
        platform=PLATFORM,
        name=_text(d.get("title")),
        avatar_url=(lambda u: "https:" + u if u and u.startswith("//") else u)(_thumb(d.get("thumbnail"))),
        url=f"{SITE}{handle}" if handle else f"{SITE}/channel/{cid}",
        bio=_text(d.get("descriptionSnippet")),
        metrics=UserMetrics(followers=_count(sub_text)),
        raw={"handle": handle, "subscriber_text": sub_text},
    )


def parse_search_users(raw: Any) -> dict:
    users = [u for d in _walk(_payload(raw), lambda d: "channelId" in d and "title" in d and "subscribeButton" in d) if (u := _channel(d))]
    return _list_result(users, _tab(raw), _has_continuation(raw))


def parse_get_user(raw: Any) -> dict:
    data = _payload(raw)
    meta = (data.get("metadata") or {}).get("channelMetadataRenderer") or {}
    if not meta.get("externalId") and not meta.get("title"):
        raise ValueError("channel metadata not found")
    header = data.get("header") or {}
    header_text = " ".join(t for t in (_text(x) for x in _walk(header, lambda d: "content" in d and isinstance(d.get("content"), str))) if t)
    subs = None
    for m in re.finditer(r"([\d.,]+\s*[万亿KMB]?)\s*(位订阅者|subscribers)", header_text):
        subs = _count(m.group(1))
        break
    videos = None
    for m in re.finditer(r"([\d.,]+\s*[万亿KMB]?)\s*(个视频|videos)", header_text):
        videos = _count(m.group(1))
        break
    handle = meta.get("vanityChannelUrl", "").split("youtube.com/")[-1] if meta.get("vanityChannelUrl") else None
    return SocialUser(
        id=str(meta.get("externalId") or handle),
        platform=PLATFORM,
        name=meta.get("title"),
        avatar_url=_thumb(meta.get("avatar")),
        url=meta.get("channelUrl") or (f"{SITE}/{handle}" if handle else None),
        bio=meta.get("description"),
        metrics=UserMetrics(followers=subs, posts=videos),
        raw={"handle": handle, "keywords": meta.get("keywords"), "header_text": header_text[:300]},
    ).model_dump()


# ---- video detail ----------------------------------------------------------------


def _likes(data: Any) -> int | None:
    """Like count from the watch page: factoidRenderer labelled 赞/likes, else the like button's
    accessibility text ("与另外 957,544 人一起顶此视频" / "like this video along with 957,544 other people")."""
    for d in _walk(data, lambda d: isinstance(d.get("factoidRenderer"), dict)):
        f = d["factoidRenderer"]
        label = (_text(f.get("label")) or "") + " " + str(f.get("accessibilityText") or "")
        if re.search(r"赞|like", label, re.I):
            n = _count(f.get("value"))
            if n:
                return n
    for d in _walk(data, lambda d: "likeCountIfIndifferent" in d or "likeCountIfLiked" in d):
        n = _count(d.get("likeCountIfIndifferent")) or _count(d.get("likeCountIfLiked"))
        if n:
            return n
    for d in _walk(data, lambda d: isinstance(d.get("accessibilityText"), str) and re.search(r"顶此视频|like this video|赞", d["accessibilityText"])):
        m = re.search(r"\d[\d,]*", d["accessibilityText"])
        if m:
            return int(m.group().replace(",", ""))
    return None


def parse_get_post(raw: Any) -> dict:
    if not isinstance(raw, dict) or not raw.get("ssr"):
        raise ValueError("expected {player, data}")
    player = raw.get("player") or {}
    vd = player.get("videoDetails") or {}
    if not vd.get("videoId"):
        raise ValueError("videoDetails missing (age-restricted, private, or page changed)")
    mf = ((player.get("microformat") or {}).get("playerMicroformatRenderer")) or {}
    data = raw.get("data") or {}
    likes = _likes(data)
    comments = None
    for d in _walk(data, lambda d: "commentCount" in d):
        comments = _count(d.get("commentCount"))
        if comments:
            break
    published = mf.get("publishDate") or mf.get("uploadDate")
    if published and len(published) == 10:
        published += "T00:00:00+00:00"
    return SocialPost(
        id=str(vd["videoId"]),
        platform=PLATFORM,
        type="video",
        title=vd.get("title"),
        content=vd.get("shortDescription"),
        author=SocialUser(id=str(vd.get("channelId")), platform=PLATFORM, name=vd.get("author"), url=f"{SITE}/channel/{vd.get('channelId')}") if vd.get("channelId") else None,
        url=f"{SITE}/watch?v={vd['videoId']}",
        cover_url=_thumb(mf.get("thumbnail")) or _thumb(vd.get("thumbnail")),
        media=[MediaItem(type="video", url=f"{SITE}/watch?v={vd['videoId']}", duration=float(vd.get("lengthSeconds") or 0) or None, extra={"needs_stream_resolution": True})],
        metrics=Metrics(likes=likes, comments=comments, views=_count(vd.get("viewCount"))),
        publish_time=published,
        tags=list(vd.get("keywords") or [])[:30],
        raw={"category": mf.get("category"), "is_live": vd.get("isLiveContent"), "owner_handle": (mf.get("ownerProfileUrl") or "").split("youtube.com/")[-1] or None},
    ).model_dump()


# ---- comments --------------------------------------------------------------------


def _page_token(body: Any) -> str | None:
    """Token of the trailing continuationItemRenderer among the top-level continuation items
    (reply-thread continuations live deeper, inside commentRepliesRenderer, and are skipped)."""
    token = None
    for ep in (body.get("onResponseReceivedEndpoints") or []) if isinstance(body, dict) else []:
        for key in ("reloadContinuationItemsCommand", "appendContinuationItemsAction"):
            for it in ((ep.get(key) or {}).get("continuationItems") or []):
                cir = it.get("continuationItemRenderer") if isinstance(it, dict) else None
                if cir:
                    cmd = _walk(cir, lambda d: isinstance(d.get("continuationCommand"), dict))
                    if cmd and cmd[0]["continuationCommand"].get("token"):
                        token = cmd[0]["continuationCommand"]["token"]
    return token


def _comment(d: dict) -> SocialComment | None:
    """commentRenderer (older, flat) or commentEntityPayload (newer: properties/author/toolbar)."""
    props = d.get("properties") or {}
    author = d.get("author") or {}
    toolbar = d.get("toolbar") or {}
    cid = d.get("commentId") or props.get("commentId")
    if not cid:
        return None
    content = props.get("content")
    text = _text(d.get("contentText")) or (content.get("content") if isinstance(content, dict) else None)
    name = _text(d.get("authorText")) or author.get("displayName")
    channel = author.get("channelId") or _browse(d.get("authorEndpoint"))[0]
    likes = _count(d.get("voteCount")) or _count(toolbar.get("likeCountNotliked"))
    published_text = _text(d.get("publishedTimeText")) or props.get("publishedTime")
    return SocialComment(
        id=str(cid),
        platform=PLATFORM,
        post_id=str(props.get("targetId") or ""),
        parent_id=None,
        author=SocialUser(id=str(channel or name), platform=PLATFORM, name=name, avatar_url=_thumb(d.get("authorThumbnail")) or author.get("avatarThumbnailUrl"), url=f"{SITE}/channel/{channel}" if channel else None) if name else None,
        content=text,
        likes=likes,
        publish_time=_relative_time(published_text),
        raw={
            "published_text": published_text,
            "reply_count": _count(toolbar.get("replyCount")) or _count(d.get("replyCount")),
            "is_creator": author.get("isCreator"),
            "is_verified": author.get("isVerified"),
        },
    )


def parse_get_comments(raw: Any) -> dict:
    body = _payload(raw)
    seen: set[str] = set()
    items: list[SocialComment] = []
    # commentViewModel entries also carry commentId but no content: only renderers / entity payloads count
    for d in _walk(body, lambda d: ("commentId" in d and "contentText" in d) or (isinstance(d.get("properties"), dict) and "commentId" in d["properties"])):
        c = _comment(d)
        if c and c.id not in seen:
            seen.add(c.id)
            items.append(c)
    # replies continuation per thread: commentThreadRenderer.replies.commentRepliesRenderer -> continuation token
    tokens: dict[str, str] = {}
    for th in _walk(body, lambda d: isinstance(d.get("commentThreadRenderer"), dict)):
        t = th["commentThreadRenderer"]
        cid = ((t.get("commentViewModel") or {}).get("commentViewModel") or t.get("commentViewModel") or {}).get("commentId") or ((t.get("comment") or {}).get("commentRenderer") or {}).get("commentId")
        cmd = _walk(t.get("replies") or {}, lambda d: isinstance(d.get("continuationCommand"), dict))
        if cid and cmd and cmd[0]["continuationCommand"].get("token"):
            tokens[str(cid)] = cmd[0]["continuationCommand"]["token"]
    for c in items:
        if c.id in tokens:
            c.raw["replies_token"] = tokens[c.id]
    total = None
    for h in _walk(body, lambda d: isinstance(d.get("commentsHeaderRenderer"), dict)):
        total = _count(h["commentsHeaderRenderer"].get("countText")) or _count(h["commentsHeaderRenderer"].get("commentsCount"))
        if total:
            break
    tab = _tab(raw)
    token = _page_token(body)
    cursor = encode_cursor({"tab": tab, "token": token}) if (items and tab and token) else None
    return {"items": [c.model_dump() for c in items], "cursor": cursor, "total": total}


# ---- streams (download) ------------------------------------------------------------


def parse_get_streams(raw: Any) -> dict:
    """Passthrough of ytInitialPlayerResponse.streamingData (+ videoId)."""
    if not isinstance(raw, dict):
        raise ValueError("expected {streamingData}")
    return raw


def pick_stream_source(streams: Any) -> list[dict]:
    """Best progressive (video+audio in one file) format that carries a plain url."""
    sd = (streams or {}).get("streamingData") or {}
    formats = [f for f in sd.get("formats") or [] if isinstance(f, dict) and f.get("url") and "video/mp4" in str(f.get("mimeType", ""))]
    if not formats:
        return []
    formats.sort(key=lambda f: (int(f.get("height") or 0), int(f.get("bitrate") or 0)), reverse=True)
    f = formats[0]
    size = f.get("contentLength")
    return [{"index": 0, "type": "video", "url": f["url"], "ext": "mp4", "quality": f.get("qualityLabel"), "width": f.get("width"), "height": f.get("height"), "size": int(size) if str(size).isdigit() else None, "headers": {}}]


def parse_get_replies(raw: Any) -> dict:
    """Reply continuation response: same comment payloads; parent is the comment the page action resolved."""
    out = parse_get_comments(raw)
    parent = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    for c in out["items"]:
        if c["id"] != parent:
            c["parent_id"] = parent or None
    out["items"] = [c for c in out["items"] if c["id"] != parent]
    return out


def parse_get_trending(raw: Any) -> dict:
    out = parse_search_posts(raw)
    out["kind"] = "posts"
    return out

