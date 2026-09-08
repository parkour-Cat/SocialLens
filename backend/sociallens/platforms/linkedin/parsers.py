"""Raw LinkedIn voyager payloads -> unified models.

Voyager answers are "normalized" JSON: {"data": {...}, "included": [entities]} where references are
`*field` strings holding entity URNs. Recorded 2026-09-08 (see docs/platforms/linkedin.md):
- /feed/updatesV2?q=chronFeed: data.*elements[] -> included UpdateV2 {actor, commentary, content,
  *socialDetail, updateMetadata{urn}}; SocialDetail -> *totalSocialActivityCounts -> SocialActivityCounts
  {numLikes, numComments, numShares}; MiniProfile / MiniCompany for actors.
- /feed/updates/urn:li:activity:{id}: data is the UpdateV2 itself, included holds Comment entities.
- /identity/dash/profiles?q=memberIdentity: included Profile {firstName, lastName, headline,
  publicIdentifier, entityUrn (fsd_profile), profilePicture.displayImageReference.vectorImage}.
- /graphql voyagerSearchDashClusters (PEOPLE): included EntityResultViewModel {title.text,
  primarySubtitle.text, secondarySubtitle.text, navigationUrl, entityUrn, image} (+ Profile stubs).
- /voyagerSearchDashTypeahead: data.elements[] {title.text, subtitle.text, navigationUrl, trackingUrn}.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "linkedin"
SITE = "https://www.linkedin.com"


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ts_ms(v: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(v) / 1000, tz=timezone.utc).isoformat(timespec="seconds") if v else None
    except (TypeError, ValueError, OSError):
        return None


def _body(raw: Any) -> dict:
    if isinstance(raw, dict) and raw.get("end") is True:
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict) and "url" in raw:
        return raw["body"]
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):  # server-rendered <code> block
        try:
            return json.loads(raw["text"])
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _tab(raw: Any) -> int | None:
    return raw.get("_tab") if isinstance(raw, dict) else None


def _graphql_data(b: dict) -> dict:
    d = b.get("data") if isinstance(b.get("data"), dict) else {}
    return d.get("data") if isinstance(d.get("data"), dict) else d


class _Store:
    """Entity lookup over `included` by entityUrn / urn."""

    def __init__(self, body: dict):
        self.by_urn: dict[str, dict] = {}
        for e in body.get("included") or []:
            if isinstance(e, dict):
                for k in ("entityUrn", "urn", "dashEntityUrn"):
                    if isinstance(e.get(k), str):
                        self.by_urn.setdefault(e[k], e)

    def get(self, urn: Any) -> dict:
        return self.by_urn.get(urn, {}) if isinstance(urn, str) else {}

    def of_type(self, suffix: str) -> list[dict]:
        return [e for e in self.by_urn.values() if str(e.get("$type", "")).endswith(suffix)]


def _text(tv: Any) -> str | None:
    """TextViewModel {text} (possibly nested under `text`)."""
    if isinstance(tv, dict):
        t = tv.get("text")
        if isinstance(t, dict):
            t = t.get("text")
        return t.strip() if isinstance(t, str) and t.strip() else None
    return tv.strip() if isinstance(tv, str) and tv.strip() else None


def _vector_image(vi: Any) -> str | None:
    """VectorImage {rootUrl, artifacts[{fileIdentifyingUrlPathSegment, width}]} -> largest url."""
    if not isinstance(vi, dict):
        return None
    root = vi.get("rootUrl") or ""
    arts = [a for a in vi.get("artifacts") or [] if isinstance(a, dict) and a.get("fileIdentifyingUrlPathSegment")]
    if not arts:
        return None
    best = max(arts, key=lambda a: _int(a.get("width")) or 0)
    return root + best["fileIdentifyingUrlPathSegment"]


def _image_from(obj: Any, store: _Store) -> str | None:
    """ImageViewModel / picture objects in either the classic or dash shapes."""
    if not isinstance(obj, dict):
        return None
    for attr in obj.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        if attr.get("vectorImage"):
            return _vector_image(attr["vectorImage"])
        for ref in ("*miniProfile", "*miniCompany"):
            ent = store.get(attr.get(ref))
            pic = ent.get("picture") or ent.get("logo")
            if isinstance(pic, dict):
                u = _vector_image(pic.get("com.linkedin.common.VectorImage") or pic)
                if u:
                    return u
        if isinstance(attr.get("detailData"), dict):
            dd = attr["detailData"]
            for v in dd.values():
                u = _vector_image(v.get("vectorImage") if isinstance(v, dict) else None) or _vector_image(v)
                if u:
                    return u
    dref = obj.get("displayImageReference")
    if isinstance(dref, dict):
        return _vector_image(dref.get("vectorImage"))
    return None


def _actor_user(actor: Any, store: _Store) -> SocialUser | None:
    if not isinstance(actor, dict):
        return None
    urn = str(actor.get("urn") or "")
    name = _text(actor.get("name"))
    nav = actor.get("navigationUrl") or ((actor.get("name") or {}).get("attributes") or [{}])[0].get("navigationUrl") if isinstance(actor.get("name"), dict) else None
    ident = re.search(r"/in/([^/?#]+)|/company/([^/?#]+)", str(nav or ""))
    vanity = (ident.group(1) or ident.group(2)) if ident else None
    return SocialUser(
        id=vanity or urn.split(":")[-1],
        platform=PLATFORM,
        name=name,
        avatar_url=_image_from(actor.get("image"), store),
        url=nav or (f"{SITE}/company/{urn.split(':')[-1]}/" if ":company:" in urn else None),
        bio=_text(actor.get("description")),
        raw={"urn": urn, "kind": "company" if ":company:" in urn else "member", "sub": _text(actor.get("subDescription"))},
    )


def _content_media(content: Any, store: _Store) -> list[MediaItem]:
    out: list[MediaItem] = []
    if not isinstance(content, dict):
        return out
    for key, val in content.items():
        if not isinstance(val, dict):
            continue
        key = key[0].upper() + key[1:]  # dash payloads use lowerCamel component keys
        if "ImageComponent" in key:
            for im in val.get("images") or []:
                u = _image_from(im, store)
                if u:
                    out.append(MediaItem(type="image", url=u))
        elif "LinkedInVideoComponent" in key:
            vp = val.get("*videoPlayMetadata")
            meta = store.get(vp) if isinstance(vp, str) else (val.get("videoPlayMetadata") or {})
            prog = [p for p in (meta.get("progressiveStreams") or []) if isinstance(p, dict) and p.get("streamingLocations")]
            if prog:
                best = max(prog, key=lambda p: _int(p.get("width")) or 0)
                out.append(MediaItem(type="video", url=best["streamingLocations"][0].get("url", ""), width=_int(best.get("width")), height=_int(best.get("height")), duration=(_int(meta.get("duration")) or 0) / 1000 or None, extra={"cover_url": _vector_image((meta.get("thumbnail") or {}).get("com.linkedin.common.VectorImage") or meta.get("thumbnail"))}))
            elif meta.get("adaptiveStreams"):
                out.append(MediaItem(type="video", url=str(((meta["adaptiveStreams"][0].get("masterPlaylists") or [{}])[0]).get("url") or ""), extra={"dash": True}))
        elif "ArticleComponent" in key:
            u = _image_from(val.get("largeImage"), store)
            if u:
                out.append(MediaItem(type="image", url=u, extra={"article_url": val.get("navigationContext", {}).get("actionTarget") if isinstance(val.get("navigationContext"), dict) else None}))
    return [m for m in out if m.url]


def _counts(update: dict, store: _Store) -> Metrics:
    sd = store.get(update.get("*socialDetail"))
    counts = store.get(sd.get("*totalSocialActivityCounts")) if sd else {}
    return Metrics(likes=_int(counts.get("numLikes")), comments=_int(counts.get("numComments")), shares=_int(counts.get("numShares") if counts.get("numShares") is not None else sd.get("totalShares")))


def _update_post(update: dict, store: _Store) -> SocialPost | None:
    meta = update.get("updateMetadata") or {}
    urn = str(meta.get("urn") or update.get("entityUrn") or "")
    m = re.search(r"urn:li:(?:activity|ugcPost|share):(\d+)", urn) or re.search(r"urn:li:(?:activity|ugcPost|share):(\d+)", str(update.get("entityUrn") or ""))
    if not m:
        return None
    aid = m.group(1)
    commentary = _text(update.get("commentary"))
    content = update.get("content") if isinstance(update.get("content"), dict) else {}
    media = _content_media(content, store)
    reshared = update.get("resharedUpdate") if isinstance(update.get("resharedUpdate"), dict) else None
    article = next((v for k, v in content.items() if "ArticleComponent" in k and isinstance(v, dict)), None)
    ptype = "video" if any(x.type == "video" for x in media) else "image" if media and not article else "article" if article else "text"
    return SocialPost(
        id=aid,
        platform=PLATFORM,
        type=ptype,
        title=_text(article.get("title")) if article else None,
        content=commentary,
        author=_actor_user(update.get("actor"), store),
        url=f"{SITE}/feed/update/urn:li:activity:{aid}/",
        cover_url=(media[0].extra.get("cover_url") if media and media[0].type == "video" else media[0].url) if media else None,
        media=media,
        metrics=_counts(update, store),
        publish_time=None,
        tags=[],
        raw={"urn": urn, "posted": _text((update.get("actor") or {}).get("subDescription")), "reshare_of": _text(reshared.get("commentary")) if reshared else None, "reshare_actor": _text((reshared.get("actor") or {}).get("name")) if reshared else None, "article_url": (article.get("navigationContext") or {}).get("actionTarget") if article else None},
    )


def parse_get_feed(raw: Any) -> dict:
    b = _body(raw)
    store = _Store(b)
    data = b.get("data") or {}
    refs = data.get("*elements") or []
    updates = [store.get(r) for r in refs] if refs else [e for e in store.of_type(".UpdateV2")]
    items = [p for u in updates if u and (p := _update_post(u, store))]
    paging = data.get("paging") or {}
    start, count, total = _int(paging.get("start")) or 0, _int(paging.get("count")) or len(items), _int(paging.get("total"))
    token = (data.get("metadata") or {}).get("paginationToken")
    has_more = bool(items) and (total is None or start + count < total)
    return {"items": [i.model_dump() for i in items], "cursor": encode_cursor({"start": start + count, "token": token}) if has_more else None, "total": total}


def _comment(c: dict, store: _Store, post_id: str) -> SocialComment | None:
    m = re.search(r"\(activity:(\d+),(\d+)\)", str(c.get("urn") or "")) or re.search(r"urn:li:comment:\(([^,]+),(\d+)\)", str(c.get("urn") or ""))
    cid = m.group(2) if m else str(c.get("urn") or c.get("entityUrn") or "")
    if not cid:
        return None
    commenter = c.get("commenter") if isinstance(c.get("commenter"), dict) else {}
    mp = store.get(commenter.get("*miniProfile"))
    counts = store.get((store.get(c.get("*socialDetail")) or {}).get("*totalSocialActivityCounts"))
    parent = re.search(r",(\d+)\)", str(c.get("parentCommentUrn") or ""))
    return SocialComment(
        id=cid,
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent.group(1) if parent else None,
        author=SocialUser(id=mp.get("publicIdentifier") or str(commenter.get("urn") or "").split(":")[-1], platform=PLATFORM, name=" ".join(x for x in (mp.get("firstName"), mp.get("lastName")) if x) or _text(commenter.get("name")) or None, avatar_url=_vector_image((mp.get("picture") or {}).get("com.linkedin.common.VectorImage")), url=f"{SITE}/in/{mp['publicIdentifier']}/" if mp.get("publicIdentifier") else None, bio=mp.get("occupation") or _text(commenter.get("subDescription"))),
        content=_text(c.get("commentV2")) or _text(c.get("comment")),
        likes=_int(counts.get("numLikes")),
        publish_time=_ts_ms(c.get("createdTime")),
        raw={"reply_count": _int(counts.get("numComments")), "pinned": c.get("pinned"), "permalink": c.get("permalink")},
    )


def parse_get_post(raw: Any) -> dict:
    b = _body(raw)
    store = _Store(b)
    # /feed/updates/{urn} answers a thin Update in `data`; the UpdateV2 with commentary / actor sits in `included`
    data = b.get("data") if isinstance(b.get("data"), dict) else {}
    want = str(data.get("urn") or "")
    ups = store.of_type(".UpdateV2")
    update = next((u for u in ups if want and want in str((u.get("updateMetadata") or {}).get("urn") or "")), ups[0] if ups else data)
    p = _update_post(update, store) if update else None
    if not p:
        raise ValueError("post not found in the voyager answer (removed, or not visible to this account)")
    comments = [c for e in store.of_type(".Comment") if (c := _comment(e, store, p.id))]
    p.raw = {**(p.raw or {}), "comments": [c.model_dump() for c in comments]}
    return p.model_dump()


def parse_get_user(raw: Any) -> dict:
    b = _body(raw)
    store = _Store(b)
    profiles = store.of_type(".Profile")
    if not profiles:
        raise ValueError("profile not found (private, removed, or voyager changed)")
    # the answer also carries the viewer's own profile: take the one the request asked for when we can tell
    url = str(raw.get("url") or "") if isinstance(raw, dict) else ""
    m = re.search(r"memberIdentity=([^&]+)", url)
    want = str((raw.get("_id") if isinstance(raw, dict) else None) or (m.group(1) if m else "")).lower()
    prof = next((x for x in profiles if want and str(x.get("publicIdentifier") or "").lower() == want), None) or profiles[-1]
    pic = ((prof.get("profilePicture") or {}).get("displayImageReference") or {}).get("vectorImage")
    geo = store.get((prof.get("geoLocation") or {}).get("*geo")) if isinstance(prof.get("geoLocation"), dict) else {}
    u = SocialUser(
        id=str(prof.get("publicIdentifier") or prof.get("entityUrn") or ""),
        platform=PLATFORM,
        name=" ".join(x for x in (prof.get("firstName"), prof.get("lastName")) if x) or None,
        avatar_url=_vector_image(pic),
        url=f"{SITE}/in/{prof.get('publicIdentifier')}/" if prof.get("publicIdentifier") else None,
        bio=prof.get("headline") or None,
        metrics=UserMetrics(),
        raw={"urn": prof.get("entityUrn"), "location": geo.get("defaultLocalizedName") or geo.get("defaultLocalizedNameWithoutCountryName"), "premium": prof.get("premium"), "influencer": prof.get("influencer"), "verified": prof.get("showVerificationBadge")},
    )
    return u.model_dump()


def parse_search_users(raw: Any) -> dict:
    b = _body(raw)
    store = _Store(b)
    items: list[SocialUser] = []
    results = store.of_type("EntityResultViewModel")
    if results:
        for e in results:
            nav = str(e.get("navigationUrl") or "")
            m = re.search(r"/in/([^/?#]+)", nav)
            if not m:
                continue
            items.append(SocialUser(id=m.group(1), platform=PLATFORM, name=_text(e.get("title")), avatar_url=_image_from(e.get("image"), store), url=f"{SITE}/in/{m.group(1)}/", bio=_text(e.get("primarySubtitle")), raw={"location": _text(e.get("secondarySubtitle")), "urn": e.get("trackingUrn") or e.get("entityUrn"), "summary": _text(e.get("summary"))}))
        meta = ((b.get("data") or {}).get("data") or {}).get("searchDashClustersByAll", {}).get("metadata") or {}
        total = _int(meta.get("totalResultCount"))
        url = str(raw.get("url") or "") if isinstance(raw, dict) else ""
        start = _int((re.search(r"start:(\d+)", url) or [None, 0])[1]) or 0
        has_more = bool(items) and (total is None or start + 10 < total)
        return {"items": [u.model_dump() for u in items], "cursor": encode_cursor({"start": start + 10}) if has_more else None, "total": total}
    for raw_e in (b.get("data") or {}).get("elements") or []:  # typeahead fallback: {entityLockupView{title,subtitle,navigationUrl,image}}
        e = raw_e.get("entityLockupView") if isinstance(raw_e.get("entityLockupView"), dict) else raw_e
        nav = str(e.get("navigationUrl") or "")
        m = re.search(r"/in/([^/?#]+)", nav)
        if not m:
            continue
        items.append(SocialUser(id=m.group(1), platform=PLATFORM, name=_text(e.get("title")), avatar_url=_image_from(e.get("image"), store), url=f"{SITE}/in/{m.group(1)}/", bio=_text(e.get("subtitle")), raw={"urn": e.get("trackingUrn")}))
    return {"items": [u.model_dump() for u in items], "cursor": None, "total": len(items) or None}


# ---- classic-page captures (dash GraphQL) --------------------------------------------------------


def _dash_comment(c: dict, store: _Store, post_id: str, parent_id: str | None) -> SocialComment | None:
    m = re.search(r"fsd_comment:\((\d+),", str(c.get("entityUrn") or "")) or re.search(r",(\d+)\)", str(c.get("urn") or ""))
    if not m:
        return None
    cm = c.get("commenter") if isinstance(c.get("commenter"), dict) else {}
    nav = str(cm.get("navigationUrl") or "")
    vm = re.search(r"/in/([^/?#]+)|/company/([^/?#]+)", nav)
    counts = store.get((store.get(c.get("*socialDetail")) or {}).get("*totalSocialActivityCounts"))
    likes = _int(counts.get("numLikes"))
    if likes is None and isinstance(counts.get("reactionTypeCounts"), list):
        likes = sum(_int(x.get("count")) or 0 for x in counts["reactionTypeCounts"] if isinstance(x, dict))
    return SocialComment(
        id=m.group(1),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=SocialUser(id=(vm.group(1) or vm.group(2)) if vm else str(cm.get("commenterProfileId") or ""), platform=PLATFORM, name=_text(cm.get("title")), avatar_url=_image_from(cm.get("image"), store), url=nav.split("?")[0] or None, bio=_text(cm.get("subtitle")), raw={"is_author": cm.get("author")}),
        content=_text(c.get("commentary")),
        likes=likes,
        publish_time=_ts_ms(c.get("createdAt")),
        raw={"reply_count": _int(counts.get("numComments")), "pinned": c.get("pinned"), "edited": c.get("edited"), "permalink": c.get("permalink")},
    )


def parse_get_user_posts(raw: Any) -> dict:
    """feedDashProfileUpdatesByMemberShareFeed: *elements -> included dash Updates; paginationToken names the next page."""
    b = _body(raw)
    store = _Store(b)
    coll = _graphql_data(b).get("feedDashProfileUpdatesByMemberShareFeed") or {}
    refs = coll.get("*elements") or []
    updates = [store.get(r) for r in refs] if refs else store.of_type(".Update")
    items = [p for u in updates if u and (p := _update_post(u, store))]
    token = (coll.get("metadata") or {}).get("paginationToken")
    return {"items": [i.model_dump() for i in items], "cursor": encode_cursor({"tab": _tab(raw)}) if (items and token and _tab(raw)) else None, "total": None}


def _post_id_of(raw: Any) -> str:
    if isinstance(raw, dict) and raw.get("_post_id"):
        return str(raw["_post_id"])
    m = re.search(r"urn:li:activity:(\d+)", str(raw.get("url") or raw.get("href") or "")) if isinstance(raw, dict) else None
    return m.group(1) if m else ""


def parse_get_comments(raw: Any) -> dict:
    """Page 1: the classic post page's embedded block (the update's SocialDetail lists the top-level
    comments); later pages: socialDashCommentsBySocialDetail captures (paging.start/count/total)."""
    b = _body(raw)
    store = _Store(b)
    pid = _post_id_of(raw)
    coll = _graphql_data(b).get("socialDashCommentsBySocialDetail")
    if isinstance(coll, dict):
        refs = coll.get("*elements") or []
        paging = coll.get("paging") or {}
        total = _int(paging.get("total"))
        has_more = (_int(paging.get("start")) or 0) + (_int(paging.get("count")) or 0) < (total or 0)
    else:
        update = next((u for u in store.of_type(".Update") if pid and pid in str(u.get("entityUrn") or "")), None) or next(iter(store.of_type(".Update")), {})
        sd = store.get(update.get("*socialDetail")) if update else {}
        comments = sd.get("comments") if isinstance(sd.get("comments"), dict) else {}
        refs = comments.get("*elements") or []
        paging = comments.get("paging") or {}
        total = _int(paging.get("total"))
        has_more = (_int(paging.get("count")) or 0) < (total or 0)
        if not refs:  # no thread listing: every comment in the block
            refs = [c.get("entityUrn") for c in store.of_type(".Comment")]
    items = [c for r in refs if (e := store.get(r)) and (c := _dash_comment(e, store, pid, None))]
    return {"items": [c.model_dump() for c in items], "cursor": encode_cursor({"tab": _tab(raw)}) if (items and has_more and _tab(raw)) else None, "total": total}


def parse_get_replies(raw: Any) -> dict:
    """socialDashCommentsByRepliesByCursor: included Comments are the replies; replyNextCursor names the next page."""
    b = _body(raw)
    store = _Store(b)
    pid = _post_id_of(raw)
    parent = str((raw.get("_comment_id") if isinstance(raw, dict) else "") or "")
    coll = _graphql_data(b).get("socialDashCommentsByRepliesByCursor") or {}
    refs = coll.get("*elements") if isinstance(coll, dict) else None
    has_more = bool(((coll.get("metadata") or {}) if isinstance(coll, dict) else {}).get("replyNextCursor"))
    total = None
    if not refs and isinstance(raw, dict) and raw.get("ssr"):
        # the post page block: the parent comment's SocialDetail lists the replies shown inline
        sd = next((x for x in store.of_type(".SocialDetail") if f"urn:li:comment:(activity:{pid},{parent})" in str(x.get("entityUrn") or "")), {})
        comments = sd.get("comments") if isinstance(sd.get("comments"), dict) else {}
        refs = comments.get("*elements") or []
        paging = comments.get("paging") or {}
        total = _int(paging.get("total"))
        has_more = len(refs) < (total or 0)
    entities = [store.get(r) for r in refs] if refs else store.of_type(".Comment")
    items = [c for e in entities if e and (c := _dash_comment(e, store, pid, parent or None)) and c.id != parent]
    return {"items": [c.model_dump() for c in items], "cursor": encode_cursor({"tab": _tab(raw)}) if (items and has_more and _tab(raw)) else None, "total": total}
