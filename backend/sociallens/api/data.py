"""Platform-agnostic data routes. Each maps to a capability action; the adapter parses."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel
from fastapi import APIRouter, Query, Request

from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["data"])


def _adapter(request: Request, platform: str):
    adapter = state(request).registry.get(platform)
    if adapter is None or platform.startswith("_"):
        raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {platform}")
    return adapter


async def _run(request: Request, platform: str, action: str, params: dict[str, Any], kind: str | None = None, source: str = "api"):
    _adapter(request, platform)
    st = state(request)
    params = {k: v for k, v in params.items() if v is not None}
    instance = request.headers.get("x-sociallens-instance")
    if instance:
        params["_instance"] = instance  # pin to one extension instance (see hub.pick)
    if request.headers.get("x-sociallens-allow-anonymous") == "1":
        params["allow_anonymous"] = True  # dev/testing: skip the login gate
    task = await st.tasks.run(platform, action, params)
    result = task.result
    extra: dict[str, Any] = {"task_id": task.id}
    if isinstance(result, dict) and "items" in result:
        extra["cursor"] = result.get("cursor")
        if kind:
            st.db.upsert_items(kind, platform, result["items"])
            if result["items"]:
                extra["query_id"] = st.db.save_query(platform, action, params, kind, result["items"], source=source, task_id=task.id, first_page=not params.get("cursor"))
        data: Any = {"items": result["items"], "total": result.get("total")}
        if result.get("kind"):
            data["kind"] = result["kind"]  # "posts" | "topics" (trending lists)
    else:
        if kind and isinstance(result, dict) and result.get("id"):
            st.db.upsert_items(kind, platform, [result])
        data = result
    return ok(data, platform=platform, **extra)


@router.get("/{platform}/search")
async def search(
    request: Request,
    platform: str,
    keyword: str = Query(min_length=1),
    type: str = Query(default="post", pattern="^(post|user)$"),
    cursor: str | None = None,
    order: str | None = None,
):
    """Search a platform. type=post: posts / videos / notes; type=user: accounts. order is platform-specific. Paginate with cursor."""
    action = "search_posts" if type == "post" else "search_users"
    return await _run(request, platform, action, {"keyword": keyword, "cursor": cursor, "order": order}, kind="posts" if type == "post" else "users")


def _quota(request: Request, platform: str) -> dict[str, Any]:
    """Page-load budget of one platform queue (what risk control actually counts)."""
    st = state(request)
    rl = st.registry.get(platform).rate_limit
    q = st.tasks.status().get(platform) or {}
    return {
        "page_loads_used": q.get("page_loads_in_window", 0),
        "page_loads": rl.page_loads,
        "window_s": rl.window_s,
        "budget_wait_s": q.get("budget_wait_s", 0),
        "paused_for_s": q.get("paused_for_s", 0),
    }


@router.get("/search")
async def search_all(
    request: Request,
    keyword: str = Query(min_length=1),
    platforms: str = Query(min_length=1, description="comma-separated platform ids"),
    type: str = Query(default="post", pattern="^(post|user)$"),
):
    """Search several platforms at once with one keyword (platforms is comma-separated). Every platform runs in its own queue, in parallel, under its own rate limit and page-load budget, so this costs each platform exactly one page load, the same as searching it alone. One page per platform, no retries: a platform that fails or hits risk control is reported in its own entry and does not affect the others. Results stay grouped per platform (metrics are not comparable across sites); page on with /{platform}/search and that entry's cursor. quota shows each platform's page-load budget."""
    ids: list[str] = []
    for pid in (p.strip() for p in platforms.split(",")):
        if pid and pid not in ids:
            _adapter(request, pid)  # unknown names fail the whole call: a typo should be loud
            ids.append(pid)
    action = "search_posts" if type == "post" else "search_users"
    kind = "posts" if type == "post" else "users"

    async def one(pid: str) -> dict[str, Any]:
        entry: dict[str, Any] = {"platform": pid, "items": [], "total": None, "cursor": None, "task_id": None, "error": None}
        try:
            state(request).tasks.note_context(pid, "multi_search")
            r = await _run(request, pid, action, {"keyword": keyword}, kind=kind, source="multi_search")
            entry.update(items=r["data"]["items"], total=r["data"].get("total"), cursor=r.get("cursor"), task_id=r.get("task_id"))
        except SocialLensError as e:
            entry["error"] = e.to_dict()
        except Exception as e:  # noqa: BLE001 - one platform must never take the others down
            entry["error"] = {"code": ErrorCode.INTERNAL.value, "message": str(e)[:300]}
        entry["quota"] = _quota(request, pid)
        return entry

    results = await asyncio.gather(*(one(pid) for pid in ids))
    return ok({"keyword": keyword, "type": type, "results": list(results)})


# `xsec_token` is a 小红书 access token attached to every note/user reference (see
# docs/platforms/xiaohongshu.md); other platforms ignore it.


@router.get("/{platform}/posts/{post_id}")
async def get_post(request: Request, platform: str, post_id: str, xsec_token: str | None = None):
    """One post / video / note / article by its platform id (小红书 needs xsec_token from the item that referenced it)."""
    return await _run(request, platform, "get_post", {"id": post_id, "xsec_token": xsec_token}, kind="posts")


@router.get("/{platform}/posts/{post_id}/comments")
async def get_comments(
    request: Request, platform: str, post_id: str, cursor: str | None = None, mode: int | None = None, xsec_token: str | None = None
):
    """Top-level comments of a post, paginated with cursor. mode: bilibili 3=hot 2=time."""
    return await _run(request, platform, "get_comments", {"post_id": post_id, "cursor": cursor, "mode": mode, "xsec_token": xsec_token}, kind="comments")


@router.get("/{platform}/posts/{post_id}/comments/{comment_id}/replies")
async def get_replies(request: Request, platform: str, post_id: str, comment_id: str, cursor: str | None = None, xsec_token: str | None = None):
    """Replies under one comment (楼中楼). Same {items, cursor, total} shape as comments; parent_id is the comment."""
    return await _run(request, platform, "get_replies", {"post_id": post_id, "comment_id": comment_id, "cursor": cursor, "xsec_token": xsec_token}, kind="comments")


@router.get("/{platform}/users/{user_id}")
async def get_user(request: Request, platform: str, user_id: str, xsec_token: str | None = None):
    """Profile of a user / channel by id or handle (youtube @handle, x screen name)."""
    return await _run(request, platform, "get_user", {"id": user_id, "xsec_token": xsec_token}, kind="users")


@router.get("/{platform}/users/{user_id}/posts")
async def get_user_posts(
    request: Request, platform: str, user_id: str, cursor: str | None = None, order: str | None = None, xsec_token: str | None = None
):
    """Posts of a user, newest first, paginated with cursor."""
    return await _run(request, platform, "get_user_posts", {"id": user_id, "cursor": cursor, "order": order, "xsec_token": xsec_token}, kind="posts")


@router.get("/{platform}/trending")
async def get_trending(request: Request, platform: str):
    """Trending list: hot posts (bilibili, youtube; data.kind=posts) or hot topics (douyin, x, xiaohongshu; data.kind=topics)."""
    return await _run(request, platform, "get_trending", {}, kind=None)


@router.get("/{platform}/feed")
async def get_feed(request: Request, platform: str, cursor: str | None = None):
    """The logged-in account's home / recommendation feed, paginated with cursor."""
    return await _run(request, platform, "get_feed", {"cursor": cursor}, kind="posts")


# ---- downloads ---------------------------------------------------------------------


class DownloadBody(BaseModel):
    media_index: int | None = None  # only this MediaItem (index in post.media); default: all
    xsec_token: str | None = None
    mode: str | None = None  # bilibili: dash | mp4
    wait: bool = False  # block until finished (up to wait_s) instead of returning at once
    wait_s: float = 600


@router.post("/{platform}/posts/{post_id}/download")
async def download_post(request: Request, platform: str, post_id: str, body: DownloadBody | None = None):
    """Download a post's media into data/downloads/{platform}/{author}/. Returns the task; poll GET /tasks/{id}."""
    _adapter(request, platform)
    st = state(request)
    body = body or DownloadBody()
    params = {k: v for k, v in {"media_index": body.media_index, "xsec_token": body.xsec_token, "mode": body.mode}.items() if v is not None}
    if request.headers.get("x-sociallens-allow-anonymous") == "1":
        params["allow_anonymous"] = True
    task = await st.downloads.start(platform, post_id, params)
    if body.wait:
        await st.downloads.wait(task, body.wait_s)
    return ok(task.public(), platform=platform, task_id=task.id)


@router.get("/downloads")
async def list_downloads(request: Request, platform: str | None = None, limit: int = 50):
    """Recent download tasks with per-file progress, paths and errors."""
    st = state(request)
    return ok([t.public() for t in st.downloads.list(platform, limit)])


# ---- multi-page collection ------------------------------------------------------------------


class CollectBody(BaseModel):
    action: str  # search_posts | search_users | get_comments | get_replies | get_user_posts | get_feed | get_trending
    params: dict[str, Any] = {}
    limit: int | None = None  # max items (default 100, cap 1000)
    max_pages: int | None = None  # default 20, cap 100
    wait: bool = False
    wait_s: float = 900


@router.post("/{platform}/collect")
async def collect(request: Request, platform: str, body: CollectBody):
    """Page through a list action in the background until limit / end of list / max_pages. Returns the task; poll GET /tasks/{id}."""
    _adapter(request, platform)
    st = state(request)
    params = dict(body.params)
    if request.headers.get("x-sociallens-allow-anonymous") == "1":
        params["allow_anonymous"] = True
    task = await st.collects.start(platform, body.action, params, body.limit, body.max_pages)
    if body.wait:
        await st.collects.wait(task, body.wait_s)
    return ok(task.public(), platform=platform, task_id=task.id)


@router.get("/collects")
async def list_collects(request: Request, platform: str | None = None, limit: int = 50):
    """Recent multi-page collect tasks with count, pages and stop reason."""
    st = state(request)
    return ok([t.public() for t in st.collects.list(platform, limit)])

