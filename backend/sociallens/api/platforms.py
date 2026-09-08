from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["platforms"])


def _adapter(request: Request, platform: str):
    adapter = state(request).registry.get(platform)
    if adapter is None or platform.startswith("_"):
        raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {platform}")
    return adapter


@router.get("/platforms")
async def list_platforms(request: Request):
    """All platforms: id, name, home / login url and hint, domains, risk level, rate limit, capabilities."""
    st = state(request)
    return ok([a.describe() for a in st.registry.all()])


@router.get("/{platform}/capabilities")
async def capabilities(request: Request, platform: str):
    """Capabilities of one platform: action, strategy (call | navigate), description, timeout."""
    adapter = _adapter(request, platform)
    return ok(adapter.describe(), platform=platform)


class RecordBody(BaseModel):
    enabled: bool


@router.post("/{platform}/record")
async def set_record(request: Request, platform: str, body: RecordBody):
    """Dev: turn record mode on/off for a platform; captured responses are saved under data/raw/{platform}/."""
    _adapter(request, platform)
    st = state(request)
    await st.hub.set_recording(platform, body.enabled)
    return ok({"recording": body.enabled}, platform=platform)


@router.get("/{platform}/raw")
async def list_raw(request: Request, platform: str, date: str | None = Query(default=None)):
    """Dev: raw captures saved by record mode for a platform on a date (default today)."""
    _adapter(request, platform)
    st = state(request)
    return ok(st.raw.list_day(platform, date), platform=platform)


class EchoBody(BaseModel):
    payload: dict = {}
    allow_anonymous: bool = False
    instance: str | None = None  # pin to one extension instance


@router.post("/{platform}/echo")
async def platform_echo(request: Request, platform: str, body: EchoBody | None = None):
    """Run an echo inside a tab of this platform. Proves page-level routing."""
    _adapter(request, platform)
    st = state(request)
    body = body or EchoBody()
    params: dict = {"payload": body.payload, "allow_anonymous": body.allow_anonymous}
    if body.instance:
        params["_instance"] = body.instance
    task = await st.tasks.run(platform, "echo", params)
    return ok(task.result, platform=platform, task_id=task.id)


@router.post("/{platform}/resume")
async def resume(request: Request, platform: str):
    """Clear a rate-limit or captcha pause on this platform's queue."""
    _adapter(request, platform)
    st = state(request)
    st.tasks.resume(platform)
    return ok(st.tasks.status().get(platform), platform=platform)


class RunBody(BaseModel):
    action: str
    params: dict = {}
    timeout_s: float | None = None
    raw: bool = False  # True = skip the adapter parser and return the raw page payload


@router.post("/{platform}/run")
async def platform_run(request: Request, platform: str, body: RunBody):
    """Development endpoint: run any declared capability or a generic page action
    (fetch / wait_capture / read_global) in this platform's tab. Used to record samples."""
    _adapter(request, platform)
    st = state(request)
    task = await st.tasks.run(platform, body.action, body.params, body.timeout_s, parse=not body.raw)
    return ok(task.result, platform=platform, task_id=task.id)
