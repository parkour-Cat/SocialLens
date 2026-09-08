"""Browse the local cache of parsed items (posts / users / comments) that data routes stored."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["items"])

KINDS = ("posts", "users", "comments")


@router.get("/items")
async def list_items(
    request: Request,
    kind: str = Query(default="posts", pattern="^(posts|users|comments)$"),
    platform: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Locally cached items (posts / users / comments) that data routes returned, newest first."""
    st = state(request)
    return ok(st.db.list_items(kind, platform, limit))


@router.get("/items/{kind}/{platform}/{item_id}")
async def get_item(request: Request, kind: str, platform: str, item_id: str):
    """One cached item by kind, platform and id."""
    if kind not in KINDS:
        raise SocialLensError(ErrorCode.NOT_FOUND, f"unknown kind {kind}")
    st = state(request)
    item = st.db.get_item(kind, platform, item_id)
    if item is None:
        raise SocialLensError(ErrorCode.NOT_FOUND, f"{kind}/{platform}/{item_id} not cached")
    return ok(item, platform=platform)
