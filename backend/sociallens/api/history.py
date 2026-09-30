"""Query history and metric snapshots: what was asked, what came back, how the numbers moved."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["history"])


@router.get("/queries")
async def list_queries(
    request: Request,
    platform: str | None = None,
    action: str | None = None,
    q: str | None = Query(default=None, description="substring of the query key (keyword / id)"),
    limit: int = 100,
    all_pages: bool = False,
):
    """Past list queries, newest first: when, platform, action, key (keyword / post id / user id), how many items, and the source (api, multi_search, collect). Every list call through the data routes is recorded with the ids it returned; cursor continuations are hidden unless all_pages=true. Use GET /queries/{id} for the items."""
    return ok(state(request).db.list_queries(platform, action, q, max(1, min(limit, 500)), all_pages))


@router.get("/queries/{query_id}")
async def get_query(request: Request, query_id: int):
    """One past query with its items as cached now, each carrying metrics_then: the newest metric snapshot at or before that query, so an old search still shows the counts of that day next to today's."""
    row = state(request).db.get_query(query_id)
    if row is None:
        raise SocialLensError(ErrorCode.NOT_FOUND, f"query {query_id} not found")
    return ok(row)


@router.get("/items/{kind}/{platform}/{item_id}/history")
async def item_history(request: Request, kind: str, platform: str, item_id: str):
    """Metric snapshots of one cached post / user, oldest first. A snapshot is written whenever an item is seen with different metrics than last time, so this is the item's growth curve as far as this tool has looked at it."""
    if kind not in ("posts", "users", "comments"):
        raise SocialLensError(ErrorCode.BAD_REQUEST, "kind must be posts, users or comments")
    return ok({"kind": kind, "platform": platform, "id": item_id, "snapshots": state(request).db.item_history(kind, platform, item_id)})
