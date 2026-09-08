"""Raw 知乎 payloads -> unified models.

Objects: answer (id, content html, voteup_count, comment_count, created_time, author, question{id,title}),
article (id, title, content, voteup_count, comment_count, created), question (id, title, detail,
answer_count, follower_count). All become SocialPost with type "text" and raw.kind = answer |
article | question. Field names are from public knowledge and MUST be re-checked against fixtures.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from ...models.social import MediaItem, Metrics, SocialComment, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "zhihu"
SITE = "https://www.zhihu.com"
_TAG_RE = re.compile(r"<[^>]+>")


def post_url(pid: str) -> str:
    """Accepts 'answer:123', 'article:123', 'question:123', a full URL, or a bare answer id."""
    pid = str(pid)
    if pid.startswith("http"):
        return pid
    kind, _, num = pid.partition(":")
    if kind == "article" or kind == "p":
        return f"https://zhuanlan.zhihu.com/p/{num}"
    if kind == "question":
        return f"{SITE}/question/{num}"
    if kind == "answer":
        return f"{SITE}/answer/{num}"
    return f"{SITE}/answer/{pid}"


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


def _text(html_: Any) -> str | None:
    if not isinstance(html_, str):
        return None
    return _TAG_RE.sub("", html_).replace("&nbsp;", " ").strip() or None


def _images(html_: Any) -> list[MediaItem]:
    if not isinstance(html_, str):
        return []
    seen: set[str] = set()
    out = []
    for m in re.finditer(r'<img[^>]+(?:data-original|src)="([^"]+)"', html_):
        u = m.group(1)
        if u.startswith("http") and u not in seen and "data:image" not in u:
            seen.add(u)
            out.append(MediaItem(type="image", url=u))
    return out


_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(obj: Any, depth: int = 0) -> Any:
    """SSR entities use camelCase (voteupCount, urlToken); the API uses snake_case. Normalise to snake."""
    if depth > 8:
        return obj
    if isinstance(obj, dict):
        return {(_CAMEL.sub("_", k).lower() if isinstance(k, str) else k): _snake(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_snake(v, depth + 1) for v in obj]
    return obj


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


def _user(a: Any) -> SocialUser | None:
    if not isinstance(a, dict) or not (a.get("url_token") or a.get("name")):
        return None
    token = a.get("url_token") or a.get("id")
    return SocialUser(
        id=str(token),
        platform=PLATFORM,
        name=_text(a.get("name")),  # search hits highlight the keyword with <em>
        avatar_url=a.get("avatar_url_template", "").replace("{size}", "xl") if a.get("avatar_url_template") else a.get("avatar_url"),
        url=f"{SITE}/people/{token}" if a.get("url_token") else None,
        bio=a.get("headline") or None,
        metrics=UserMetrics(followers=_int(a.get("follower_count")), following=_int(a.get("following_count")), posts=_int(a.get("answer_count"))),
        raw={"gender": a.get("gender"), "is_org": a.get("is_org"), "badge": [b.get("description") for b in a.get("badge") or [] if isinstance(b, dict)], "articles": _int(a.get("articles_count")), "voteup": _int(a.get("voteup_count"))},
    )


def _post(o: dict) -> SocialPost | None:
    kind = o.get("type") or ("answer" if "question" in o and "content" in o else "article" if "title" in o and "content" in o else "question" if "answer_count" in o else None)
    oid = o.get("id")
    if not oid or kind not in ("answer", "article", "question"):
        return None
    q = o.get("question") or {}
    if kind == "answer":
        url = f"{SITE}/question/{q.get('id')}/answer/{oid}" if q.get("id") else f"{SITE}/answer/{oid}"
        title = q.get("title") or q.get("name")
    elif kind == "article":
        url = f"https://zhuanlan.zhihu.com/p/{oid}"
        title = o.get("title")
    else:
        url = f"{SITE}/question/{oid}"
        title = o.get("title")
    content_html = o.get("content") or o.get("detail") or o.get("excerpt")
    media = _images(o.get("content"))
    return SocialPost(
        id=f"{kind}:{oid}",
        platform=PLATFORM,
        type="image" if media else "text",
        title=_text(title) if title and "<" in str(title) else title,
        content=_text(content_html),
        author=_user(o.get("author")),
        url=url,
        cover_url=o.get("image_url") or (media[0].url if media else None),
        media=media,
        metrics=Metrics(likes=_int(o.get("voteup_count")), comments=_int(o.get("comment_count")), collects=_int(o.get("favlists_count") if kind != "question" else o.get("follower_count")), views=_int(o.get("visit_count") if kind == "question" else None)),
        publish_time=_ts(o.get("created_time") or o.get("created")),
        tags=[t.get("name") for t in o.get("topics") or [] if isinstance(t, dict) and t.get("name")],
        raw={"kind": kind, "question_id": q.get("id"), "answer_count": _int(o.get("answer_count")), "thanks": _int(o.get("thanks_count")), "updated": _ts(o.get("updated_time") or o.get("updated")), "excerpt": o.get("excerpt")},
    )


def _search_items(body: dict) -> list[dict]:
    """search_v3 wraps hits as {type: 'search_result', object: {...}} (plus ads / cards to skip)."""
    out = []
    for it in body.get("data") or []:
        if not isinstance(it, dict):
            continue
        obj = it.get("object") if it.get("type") in ("search_result", "search_result_recall") else None
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_search_posts(raw: Any) -> dict:
    b = _body(raw)
    items = [p for o in _search_items(b) if (p := _post(o))]
    return _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))


def parse_search_users(raw: Any) -> dict:
    b = _body(raw)
    items = [u for o in _search_items(b) if (o.get("type") == "people" or "url_token" in o) and (u := _user(o))]
    return _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))


def _ssr(raw: Any) -> dict:
    """The page hands over #js-initialData as raw text (older payloads carry `data`)."""
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        return raw["data"]
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):
        import json

        try:
            return json.loads(raw["text"])
        except ValueError:
            return {}
    return {}


def parse_get_post(raw: Any) -> dict:
    """SSR initialData: initialState.entities.{answers|articles|questions}[id]."""
    data = _ssr(raw)
    ents = ((data or {}).get("initialState") or {}).get("entities") or {}
    href = str(raw.get("href") or "") if isinstance(raw, dict) else ""
    for kind, key in (("answer", "answers"), ("article", "articles"), ("question", "questions")):
        pool = ents.get(key) or {}
        m = re.search({"answer": r"/answer/(\d+)", "article": r"/p/(\d+)", "question": r"/question/(\d+)"}[kind], href)
        cand = pool.get(m.group(1)) if m else None
        if cand is None and pool and kind != "question":
            cand = next(iter(pool.values()))
        if isinstance(cand, dict):
            p = _post({**_snake(cand), "type": kind})
            if p:
                return p.model_dump()
    raise ValueError("no answer / article / question in initialData (page changed?)")


def parse_get_user(raw: Any) -> dict:
    data = _ssr(raw)
    users = (((data or {}).get("initialState") or {}).get("entities") or {}).get("users") or {}
    href = str(raw.get("href") or "") if isinstance(raw, dict) else ""
    m = re.search(r"/people/([^/?#]+)", href)
    cand = users.get(m.group(1)) if m else None
    if cand is None and users:
        cand = next(iter(users.values()))
    u = _user(_snake(cand) if isinstance(cand, dict) else cand)
    if not u:
        raise ValueError("user not found in initialData (page changed?)")
    return u.model_dump()


def parse_get_user_posts(raw: Any) -> dict:
    b = _body(raw)
    items = [p for o in b.get("data") or [] if isinstance(o, dict) and (p := _post(o))]
    return _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))


def parse_get_feed(raw: Any) -> dict:
    b = _body(raw)
    items = []
    for it in b.get("data") or []:
        target = it.get("target") if isinstance(it, dict) else None
        if isinstance(target, dict) and (p := _post(target)):
            items.append(p)
    return _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))


def parse_get_trending(raw: Any) -> dict:
    """/hot is server-rendered: initialState.topstory.hotList[] {cardId, target{titleArea, excerptArea, imageArea, metricsArea, link}, feedSpecific{answerCount}}."""
    data = _ssr(raw)
    hot = (((data or {}).get("initialState") or {}).get("topstory") or {}).get("hotList") or []
    items = []
    for i, it in enumerate(hot):
        t = it.get("target") or {} if isinstance(it, dict) else {}
        title = (t.get("titleArea") or {}).get("text")
        if not title:
            continue
        card = str(it.get("cardId") or "")
        link = (t.get("link") or {}).get("url") or (f"{SITE}/question/{card[2:]}" if card.startswith("Q_") else None)
        heat_text = (t.get("metricsArea") or {}).get("text") or ""
        m = re.search(r"([\d.]+)\s*(万)?", heat_text)
        heat = int(float(m.group(1)) * (10000 if m.group(2) else 1)) if m else None
        items.append({"rank": i + 1, "type": "topic", "platform": PLATFORM, "title": title, "url": link, "heat": heat, "description": (t.get("excerptArea") or {}).get("text"), "category": None, "raw": {"card_id": card, "answer_count": (it.get("feedSpecific") or {}).get("answerCount"), "image": (t.get("imageArea") or {}).get("url"), "heat_text": heat_text}})
    return {"items": items, "cursor": None, "total": len(items) or None, "kind": "topics"}


def _comment(c: dict, post_id: str, parent_id: str | None = None) -> SocialComment | None:
    if not c.get("id"):
        return None
    a = c.get("author") or {}
    a = a.get("member") or a
    return SocialComment(
        id=str(c["id"]),
        platform=PLATFORM,
        post_id=post_id,
        parent_id=parent_id,
        author=_user(a),
        content=_text(c.get("content")),
        likes=_int(c.get("like_count") or c.get("vote_count")),
        publish_time=_ts(c.get("created_time")),
        raw={"reply_count": _int(c.get("child_comment_count")), "is_author": c.get("is_author"), "hot": c.get("hot")},
    )


def _post_id_from_url(url: str) -> str:
    m = re.search(r"/comment_v5/(answers|articles|questions)/(\d+)", url)
    return f"{ {'answers': 'answer', 'articles': 'article', 'questions': 'question'}[m.group(1)] }:{m.group(2)}" if m else ""


def parse_get_comments(raw: Any) -> dict:
    b = _body(raw)
    post_id = _post_id_from_url(str(raw.get("url", ""))) if isinstance(raw, dict) else ""
    items = []
    for c in b.get("data") or []:
        if isinstance(c, dict) and (x := _comment(c, post_id)):
            items.append(x)
            for cc in c.get("child_comments") or []:
                if isinstance(cc, dict) and (y := _comment(cc, post_id, parent_id=str(c["id"]))):
                    items.append(y)
    out = _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))
    out["total"] = _int(b.get("total") or (b.get("paging") or {}).get("totals"))
    return out


def parse_get_replies(raw: Any) -> dict:
    b = _body(raw)
    root = str(raw.get("_comment_id") or "") if isinstance(raw, dict) else ""
    if not root:
        m = re.search(r"/comment_v5/comment/(\d+)/child_comment", str(raw.get("url", "")) if isinstance(raw, dict) else "")
        root = m.group(1) if m else ""
    items = [x for c in b.get("data") or [] if isinstance(c, dict) and (x := _comment(c, "", parent_id=root))]
    out = _list_result(items, not (b.get("paging") or {}).get("is_end", True), _tab(raw))
    if out.get("cursor") and isinstance(raw, dict) and raw.get("_snippet"):
        out["cursor"] = encode_cursor({"tab": _tab(raw), "snippet": raw["_snippet"], "page": raw.get("_page") or 1})
    return out
