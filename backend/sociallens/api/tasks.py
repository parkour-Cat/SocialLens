from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["tasks"])


class EchoBody(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    instance: str | None = None  # pin to one extension instance


@router.post("/tasks/echo")
async def echo(request: Request, body: EchoBody):
    """Round-trip through the extension service worker. The stage 0 link test."""
    st = state(request)
    params: dict[str, Any] = {"payload": body.payload}
    if body.instance:
        params["_instance"] = body.instance
    task = await st.tasks.run("_system", "echo", params)
    return ok(task.result, task_id=task.id)


@router.get("/tasks/cookies")
async def cookies(request: Request, url: str = Query(min_length=8)):
    """Dev: cookie names and domains the browser holds for a site (never values)."""
    st = state(request)
    task = await st.tasks.run("_system", "cookies", {"url": url})
    return ok(task.result, task_id=task.id)


@router.get("/tasks")
async def list_tasks(
    request: Request,
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Recent tasks, newest first; filter by platform, status, action (collect / download / ...)."""
    st = state(request)
    tasks = st.tasks.list(platform, status, 500 if action else limit)
    if action:
        tasks = [t for t in tasks if t.action == action][:limit]
    return ok([t.public() for t in tasks])


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str):
    """One task: status, params, result (progress for collect / download), error."""
    st = state(request)
    task = st.tasks.get(task_id)
    if task is None:
        raise SocialLensError(ErrorCode.NOT_FOUND, f"task {task_id} not found")
    return ok(task.public())


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str):
    """Cancel a queued or running task (downloads and collects included)."""
    st = state(request)
    task = await st.tasks.cancel(task_id)
    return ok(task.public())
