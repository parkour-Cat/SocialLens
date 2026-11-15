"""Comment digest: many comments of one post, compacted for a reader with a small budget (an LLM
over MCP, or a person skimming).

The raw comment lists are mostly platform payload (`raw`, avatars, badges); a model analysing
what an audience thinks needs the text, the likes, when, and who. The digest keeps exactly that,
puts the most-liked comments first and adds the numbers a summary should quote (how many,
over what period, how concentrated the likes are, who keeps commenting).
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

TEXT_MAX = 300
TOP_N = 20
TOP_AUTHORS = 10


def _text(s: Any, limit: int = TEXT_MAX) -> str:
    t = " ".join(str(s or "").split())  # newlines / runs of spaces -> one space
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _reply_count(c: dict) -> int | None:
    raw = c.get("raw") if isinstance(c.get("raw"), dict) else {}
    for k in ("rcount", "reply_count", "sub_comment_count", "replies", "reply_total"):
        v = raw.get(k)
        if isinstance(v, int):
            return v
    return None


def _relative(c: dict) -> str | None:
    """The site's own relative time ("1 year ago", "3天前") when that is all it gave (YouTube):
    publish_time is then only an estimate derived from it."""
    raw = c.get("raw") if isinstance(c.get("raw"), dict) else {}
    v = raw.get("published_text")
    return v if isinstance(v, str) and v else None


def _line(c: dict) -> dict[str, Any]:
    out: dict[str, Any] = {
        "likes": c.get("likes") or 0,
        "time": _relative(c) or (c.get("publish_time") or "")[:16].replace("T", " ") or None,
        "author": ((c.get("author") or {}).get("name")) or None,
        "text": _text(c.get("content")),
    }
    rc = _reply_count(c)
    if rc:
        out["replies"] = rc
    if c.get("parent_id"):
        out["reply_to"] = c["parent_id"]
    return out


def _post(p: dict | None) -> dict[str, Any] | None:
    if not isinstance(p, dict):
        return None
    return {
        "id": p.get("id"),
        "title": _text(p.get("title") or p.get("content"), 200),
        "author": (p.get("author") or {}).get("name"),
        "url": p.get("url"),
        "publish_time": p.get("publish_time"),
        "metrics": {k: v for k, v in (p.get("metrics") or {}).items() if v is not None},
    }


def comment_digest(comments: list[dict], post: dict | None = None, top_n: int = TOP_N) -> dict[str, Any]:
    """{post, stats, top_comments, others}: top_comments are the top_n by likes, others the rest
    (also by likes). Comments without text (stickers only) are counted but not listed."""
    seen: set[str] = set()
    uniq = []
    for c in comments:
        cid = str(c.get("id") or "")
        if cid and cid in seen:
            continue
        seen.add(cid)
        uniq.append(c)

    likes = [c.get("likes") or 0 for c in uniq]
    times = sorted(t for t in (c.get("publish_time") for c in uniq) if t)
    authors = Counter(n for n in ((c.get("author") or {}).get("name") for c in uniq) if n)
    days = Counter(t[:10] for t in times)
    texted = [c for c in uniq if _text(c.get("content"))]
    ranked = sorted(texted, key=lambda c: (-(c.get("likes") or 0), c.get("publish_time") or ""))
    total_likes = sum(likes)
    top_likes = sum(sorted(likes, reverse=True)[:top_n])
    p = _post(post)
    approx = any(_relative(c) for c in uniq)

    stats: dict[str, Any] = {
        "fetched": len(uniq),
        "top_level": sum(1 for c in uniq if not c.get("parent_id")),
        "replies": sum(1 for c in uniq if c.get("parent_id")),
        "without_text": len(uniq) - len(texted),
        "reported_total": (p or {}).get("metrics", {}).get("comments"),
        "first": times[0] if times else None,
        "last": times[-1] if times else None,
        "likes": {
            "sum": total_likes,
            "max": max(likes) if likes else 0,
            "median": statistics.median(likes) if likes else 0,
            # how much of the attention the top comments hold: high = a few comments dominate
            f"top{top_n}_share": round(top_likes / total_likes, 3) if total_likes else None,
        },
        # relative times ("1 year ago") pile many comments onto one estimated day: no per-day counts then
        "busiest_days": None if approx else [{"day": d, "comments": n} for d, n in days.most_common(7)],
        "repeat_authors": [{"author": a, "comments": n} for a, n in authors.most_common(TOP_AUTHORS) if n > 1],
    }
    if approx:
        stats["time_note"] = "the site gives relative times only (e.g. '1 year ago'): first/last are estimates and comment times are shown as the site wrote them"
    return {
        "post": p,
        "stats": stats,
        "top_comments": [_line(c) for c in ranked[:top_n]],
        "others": [_line(c) for c in ranked[top_n:]],
    }
