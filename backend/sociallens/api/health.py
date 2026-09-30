"""Platform health: is each platform's cheapest read still working?"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Request

from ..known_issues import KNOWN_ISSUES
from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(tags=["health"])


@router.get("/health/platforms")
async def health_platforms(request: Request):
    """Latest probe result per platform (state ok / broken / blocked / skipped, code, message, checked_at, elapsed_ms, items) with broken_since (start of the current non-ok streak) and last_ok_at; null for a platform never checked. Also the schedule interval, the id of a check in progress, and which action each platform is probed with. broken means our code or the site changed; blocked means the environment (not signed in, extension offline, captcha) prevented the check."""
    return ok(state(request).health.summary())


@router.get("/known-issues")
async def known_issues(platform: str | None = None):
    """What is known not to work and why: open bugs, code that never ran through, and limits of the sites themselves (status open / unverified / limit / by_design). Check here before debugging a platform that fails in one of these ways."""
    return ok([i for i in KNOWN_ISSUES if not platform or i["platform"] == platform])


@router.get("/risk/events")
async def risk_events(request: Request, platform: str | None = None, limit: int = 100):
    """Risk-control hits (captcha_required / rate_limited), newest first, each with the traffic that preceded it: page loads and tasks in the previous 10 and 60 minutes, actions, the tightest gap between dispatches, which callers were active (multi_search / health / collect), and the time since the platform's previous hit. Recorded only; nothing adapts to it yet. The point is to learn each site's real thresholds instead of guessing rate limits. summary gives per-platform counts and the last hit."""
    st = state(request)
    events = st.db.risk_events(platform, max(1, min(limit, 500)))
    summary: dict[str, dict] = {}
    for ev in st.db.risk_events(None, 5000):
        s = summary.setdefault(ev["platform"], {"count": 0, "last_at": ev["at"], "last_code": ev["code"]})
        s["count"] += 1
    return ok({"events": events, "summary": summary})


class CheckBody(BaseModel):
    platforms: list[str] | None = None  # default: every platform that has a probe
    wait: bool = True  # False: return the task at once, poll GET /tasks/{id}


@router.post("/health/check")
async def health_check(request: Request, body: CheckBody | None = None):
    """Probe platforms now (all probed platforms by default) and record the results. Each probe is one cheap page load in that platform's own queue, so this costs every platform one page of its budget. Platforms that are not signed in are recorded as blocked without loading a page. Returns the health task; with wait=true (default) it waits up to two minutes for the run to finish. A run already in progress is returned instead of starting another."""
    body = body or CheckBody()
    st = state(request)
    for pid in body.platforms or []:
        if st.registry.get(pid) is None:
            raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {pid}")
    task = st.health.check(body.platforms)
    if body.wait:
        await st.tasks.wait(task.id, 120.0)
    return ok(task.model_dump())
