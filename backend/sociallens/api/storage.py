"""Disk usage and cleanup of the local data directory."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .deps import ok, state

router = APIRouter(tags=["storage"])


@router.get("/storage")
async def storage_usage(request: Request):
    """Database size, rows / approximate bytes / oldest entry per table, directory sizes
    (downloads, raw, uploads, logs), the retention policy in days (0 = keep) and the last prune."""
    return ok(state(request).retention.usage())


class PruneBody(BaseModel):
    # target -> days; omit to apply the configured policy. Targets: tasks (finished only), health,
    # risk_events, queries, snapshots, items, raw, uploads. 0 removes everything in that target.
    older_than_days: dict[str, float] | None = None
    vacuum: bool | None = None  # default: compact the database when rows were removed


@router.post("/storage/prune")
async def storage_prune(request: Request, body: PruneBody | None = None):
    """Delete old data now. Downloaded media is never touched. Returns what was removed and the
    database size before / after."""
    body = body or PruneBody()
    return ok(state(request).retention.prune(body.older_than_days, body.vacuum))
