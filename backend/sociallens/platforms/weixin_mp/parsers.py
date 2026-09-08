"""Raw 公众号 payloads -> unified models."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ...models.social import MediaItem, Metrics, SocialPost, SocialUser, UserMetrics
from ..bilibili.cursor import encode_cursor

PLATFORM = "weixin_mp"
PAGE = 5


def _ts(v: Any) -> str | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if not n:
        return None
    if n > 10**12:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")


def _body(raw: Any) -> dict:
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict):
        return raw["body"]
    if isinstance(raw, dict):
        return raw
    raise ValueError("unexpected payload shape")


def _check(b: dict) -> None:
    ret = (b.get("base_resp") or {}).get("ret", 0)
    if ret:
        raise ValueError(f"公众号后台 ret={ret} {(b.get('base_resp') or {}).get('err_msg', '')}")


def _account(item: dict) -> SocialUser | None:
    fakeid = item.get("fakeid")
    if not fakeid:
        return None
    return SocialUser(
        id=str(fakeid),
        platform=PLATFORM,
        name=item.get("nickname"),
        avatar_url=item.get("round_head_img"),
        url=None,
        bio=item.get("signature"),
        metrics=UserMetrics(),
        raw={"alias": item.get("alias"), "service_type": item.get("service_type"), "verify_status": item.get("verify_status")},
    )


def parse_search_users(raw: Any) -> dict:
    b = _body(raw)
    _check(b)
    items = [u for it in b.get("list") or [] if isinstance(it, dict) and (u := _account(it))]
    begin = int(b.get("_begin", 0) or 0)
    total = b.get("total")
    has_more = len(items) >= PAGE and (total is None or begin + PAGE < int(total))
    return {"items": [u.model_dump() for u in items], "cursor": encode_cursor({"begin": begin + PAGE}) if has_more else None, "total": total}


def parse_get_user(raw: Any) -> dict:
    b = _body(raw)
    _check(b)
    accounts = [u for it in b.get("list") or [] if isinstance(it, dict) and (u := _account(it))]
    if not accounts:
        raise ValueError("no account matched")
    return accounts[0].model_dump()


def _article(a: dict) -> SocialPost | None:
    link = a.get("link")
    if not link:
        return None
    aid = str(a.get("aid") or link)
    return SocialPost(
        id=aid,
        platform=PLATFORM,
        type="article",
        title=a.get("title"),
        content=a.get("digest"),
        author=None,
        url=link,
        cover_url=a.get("cover"),
        media=[],
        metrics=Metrics(),
        publish_time=_ts(a.get("create_time")),
        raw={"update_time": _ts(a.get("update_time")), "author_name": a.get("author_name"), "item_show_type": a.get("item_show_type"), "appmsgid": a.get("appmsgid"), "itemidx": a.get("itemidx")},
    )


def parse_get_user_posts(raw: Any) -> dict:
    b = _body(raw)
    _check(b)
    items = [p for a in b.get("app_msg_list") or [] if isinstance(a, dict) and (p := _article(a))]
    total = b.get("app_msg_cnt")
    begin = int(b.get("_begin", 0) or 0)
    has_more = bool(items) and (total is None or begin + PAGE < int(total))
    return {"items": [p.model_dump() for p in items], "cursor": encode_cursor({"begin": begin + PAGE}) if has_more else None, "total": total}


# ---- article page (navigate + DOM read) ----------------------------------------------------

_WS = re.compile(r"\s+")
_CN_TIME = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")


def _cn_time(text: Any) -> str | None:
    m = _CN_TIME.search(str(text or ""))
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:00+08:00"


def parse_get_post(raw: Any) -> dict:
    if not isinstance(raw, dict) or "title" not in raw:
        raise ValueError("expected article page payload")
    images = [MediaItem(type="image", url=u, headers={"Referer": "https://mp.weixin.qq.com/"}) for u in raw.get("images") or [] if isinstance(u, str) and u.startswith("http")]
    author_name = raw.get("account_name")
    author = SocialUser(id=str(raw.get("biz") or author_name or ""), platform=PLATFORM, name=author_name, raw={"biz": raw.get("biz"), "author": raw.get("author")}) if (author_name or raw.get("biz")) else None
    text = _WS.sub(" ", str(raw.get("text") or "")).strip()
    return SocialPost(
        id=str(raw.get("id") or raw.get("url") or ""),
        platform=PLATFORM,
        type="article",
        title=(raw.get("title") or "").strip() or None,
        content=text or None,
        author=author,
        url=raw.get("url"),
        cover_url=raw.get("cover"),
        media=images,
        metrics=Metrics(),
        publish_time=raw.get("publish_time") or _cn_time(raw.get("publish_time_text")),
        raw={"html": raw.get("html"), "author": raw.get("author"), "ip_wording": raw.get("ip_wording")},
    ).model_dump()
