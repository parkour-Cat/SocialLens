"""Raw 快手 payloads -> unified models.

Payloads are Capture objects whose `body` is a GraphQL response ({"data": {<op>: ...}}).
List results return {"items", "cursor", "total"}; the cursor carries the tab id (`_tab`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "kuaishou"
SITE = "https://www.kuaishou.com"
REFERER = {"Referer": SITE + "/"}


def _count(v: Any) -> int | None:
    """快手 mixes ints with display strings like '46.4万'."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "")
    try:
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        if s.endswith("亿"):
            return int(float(s[:-1]) * 100000000)
        return int(float(s))
    except ValueError:
        return None


def _ts(v: Any) -> str | None:
    n = _count(v)
    if not n:
        return None
    if n > 10**12:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _ended(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("end") is True


def _data(raw: Any, op: str | None) -> dict:
    """GraphQL responses carry the payload under data.<op>; REST (/rest/v/...) responses are flat."""
    if _ended(raw):
        return {}
    body = raw.get("body") if isinstance(raw, dict) and "url" in raw else raw
    if not isinstance(body, dict):
        raise ValueError("unexpected payload shape")
    if body.get("errors"):
        raise ValueError(f"graphql error: {body['errors'][0].get('message') if isinstance(body['errors'], list) else body['errors']}")
    if isinstance(body.get("data"), dict):
        d = body["data"].get(op) if op else next(iter(body["data"].values()), None)
        if d is None:
            raise ValueError(f"response has no data.{op}")
        return d
    if "result" in body and body.get("result") not in (1, None):
        raise ValueError(f"request failed: result={body.get('result')} {body.get('error_msg') or ''}")
    return body


def _list_result(items: list, has_more: bool, tab: int | None, total: int | None = None) -> dict:
    return {"items": [p.model_dump() for p in items], "cursor": encode_cursor({"tab": tab}) if (has_more and tab) else None, "total": total}


def _more(d: dict, n_items: int) -> bool:
    pc = d.get("pcursor") if d.get("pcursor") not in (None, "") else d.get("pcursorV2")
    return bool(n_items) and pc not in (None, "", "no_more")


def _author(a: Any) -> SocialUser | None:
    if not isinstance(a, dict) or not a.get("id"):
        return None
    return SocialUser(
        id=str(a["id"]),
        platform=PLATFORM,
        name=a.get("name"),
        avatar_url=a.get("headerUrl") or a.get("avatar"),
        url=f"{SITE}/profile/{a['id']}",
        raw={"following": a.get("following")},
    )


def _feed_post(f: dict) -> SocialPost | None:
    ph = f.get("photo") or {}
    pid = ph.get("id")
    if not pid:
        return None
    media: list[MediaItem] = []
    urls = ph.get("photoUrls")
    play = ph.get("photoUrl") or (urls[0].get("url") if isinstance(urls, list) and urls and isinstance(urls[0], dict) else None)
    if play:
        media.append(
            MediaItem(
                type="video",
                url=play,
                width=ph.get("width"),
                height=ph.get("height"),
                duration=(_count(ph.get("duration")) or 0) / 1000 if ph.get("duration") else None,
                headers=REFERER,
                extra={"h265": ph.get("photoH265Url"), "backup_urls": [u.get("url") for u in urls[1:] if isinstance(u, dict)] if isinstance(urls, list) else [], "manifest": bool(ph.get("manifest"))},
            )
        )
    tags = [t.get("name") for t in f.get("tags") or [] if isinstance(t, dict) and t.get("name")]
    return SocialPost(
        id=str(pid),
        platform=PLATFORM,
        type="video",
        title=None,
        content=ph.get("caption") or ph.get("originCaption"),
        author=_author(f.get("author")),
        url=f"{SITE}/short-video/{pid}",
        cover_url=ph.get("coverUrl"),
        media=media,
        metrics=Metrics(
            likes=_count(ph.get("realLikeCount")) or _count(ph.get("likeCount")),
            comments=_count(ph.get("commentCount")),
            collects=_count(ph.get("collectCount")),
            views=_count(ph.get("viewCount")),
        ),
        publish_time=_ts(ph.get("timestamp")),
        tags=tags,
        raw={"like_text": ph.get("likeCount"), "type": f.get("type"), "duration_ms": ph.get("duration")},
    )


def _feed_list(raw: Any, op: str) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    d = _data(raw, op)
    posts = [p for f in d.get("feeds") or [] if isinstance(f, dict) and (p := _feed_post(f))]
    return _list_result(posts, _more(d, len(posts)), _tab(raw))


def parse_get_feed(raw: Any) -> dict:
    body = raw.get("body") if isinstance(raw, dict) and "url" in raw else raw
    op = next(iter(((body or {}).get("data") or {}).keys()), "brilliantData") if isinstance(body, dict) else "brilliantData"
    return _feed_list(raw, op)


def parse_get_user_posts(raw: Any) -> dict:
    return _feed_list(raw, None)  # REST /rest/v/profile/feed


def parse_search_posts(raw: Any) -> dict:
    return _feed_list(raw, None)  # REST /rest/v/search/feed


def parse_search_users(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    d = _data(raw, None)  # REST /rest/v/search/user
    users = []
    for u in d.get("users") or []:
        if not isinstance(u, dict) or not u.get("user_id"):
            continue
        users.append(
            SocialUser(
                id=str(u["user_id"]),
                platform=PLATFORM,
                name=u.get("user_name"),
                avatar_url=u.get("headurl"),
                url=f"{SITE}/profile/{u['user_id']}",
                bio=u.get("user_text") or None,
                raw={"verified": u.get("verified"), "is_following": u.get("isFollowing")},
            )
        )
    return _list_result(users, _more(d, len(users)), _tab(raw))


# ---- video detail (SSR: __APOLLO_STATE__) ------------------------------------------------


def parse_get_post(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("photo"), dict):
        raise ValueError("expected {photo, author}")
    ph = raw["photo"]
    post = _feed_post({"photo": ph, "author": raw.get("author") or {}, "tags": [{"name": t} for t in raw.get("tags") or []]})
    if post is None:
        raise ValueError("photo has no id")
    post.metrics.views = _count(ph.get("viewCount"))
    return post.model_dump()


# ---- profile (SSR: INIT_STATE ... userProfile) -------------------------------------------


def parse_get_user(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("user"), dict):
        raise ValueError("expected {user}")
    u = raw["user"]
    prof = u.get("profile") or {}
    counts = u.get("ownerCount") or {}
    uid = prof.get("user_id")
    if not uid:
        raise ValueError("profile has no user_id")
    avatar = prof.get("headurl")
    return SocialUser(
        id=str(uid),
        platform=PLATFORM,
        name=prof.get("user_name"),
        avatar_url=("https:" + avatar if isinstance(avatar, str) and avatar.startswith("//") else avatar),
        url=f"{SITE}/profile/{uid}",
        bio=prof.get("user_text"),
        metrics=UserMetrics(followers=_count(counts.get("fan")), following=_count(counts.get("follow")), posts=_count(counts.get("photo_public"))),
        raw={"kwai_id": u.get("userDefineId"), "gender": u.get("gender"), "likes_received": _count(counts.get("like")), "is_following": u.get("isFollowing")},
    ).model_dump()


# ---- comments (GraphQL commentListQuery -> visionCommentList) -----------------------------


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment:
    return SocialComment(
        id=str(c.get("commentId")),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=SocialUser(id=str(c.get("authorId") or ""), platform=PLATFORM, name=c.get("authorName"), avatar_url=c.get("headurl"), url=f"{SITE}/profile/{c.get('authorId')}" if c.get("authorId") else None) if c.get("authorId") else None,
        content=c.get("content"),
        likes=_count(c.get("likedCount")),
        publish_time=_ts(c.get("timestamp")),
        raw={"sub_comment_count": _count(c.get("subCommentCount")), "author_liked": c.get("authorLiked")},
    )


def parse_get_comments(raw: Any) -> dict:
    if _ended(raw):
        return _list_result([], False, None)
    d = _data(raw, "visionCommentList")
    post_id = ""
    rb = raw.get("request_body") if isinstance(raw, dict) else None
    if rb and '"photoId":"' in rb:
        post_id = rb.split('"photoId":"')[1].split('"')[0]
    items: list[SocialComment] = []
    roots = d.get("rootComments") or d.get("rootCommentsV2") or []
    for c in roots:
        if not isinstance(c, dict):
            continue
        items.append(_comment(c, post_id))
        for sc in c.get("subComments") or []:
            if isinstance(sc, dict):
                items.append(_comment(sc, post_id, parent_id=str(c.get("commentId"))))
    return _list_result(items, _more(d, len(items)) if items else False, _tab(raw), total=_count(d.get("commentCount") or d.get("commentCountV2")))


def parse_get_replies(raw: Any) -> dict:
    """GraphQL visionSubCommentList: subComments[] under rootCommentId, pcursor for more."""
    if _ended(raw):
        return _list_result([], False, None)
    d = _data(raw, "visionSubCommentList")
    root = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    rb = raw.get("request_body") if isinstance(raw, dict) else None
    post_id = rb.split('"photoId":"')[1].split('"')[0] if rb and '"photoId":"' in rb else ""
    if not root and rb and '"rootCommentId":"' in rb:
        root = rb.split('"rootCommentId":"')[1].split('"')[0]
    items = [_comment(c, post_id, parent_id=root) for c in d.get("subComments") or [] if isinstance(c, dict)]
    out = _list_result(items, _more(d, len(items)) if items else False, _tab(raw))
    if out.get("cursor") and isinstance(raw, dict) and raw.get("_snippet"):
        out["cursor"] = encode_cursor({"tab": _tab(raw), "snippet": raw["_snippet"]})
    return out

