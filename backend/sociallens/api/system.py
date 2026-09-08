from __future__ import annotations

from fastapi import APIRouter, Request

from .. import __version__
from .deps import ok, state

router = APIRouter(tags=["system"])


@router.get("/status")
async def status(request: Request):
    """Backend version, extension connections, per-platform login state and open tabs, queue state (pending, paused, page-load budget use)."""
    st = state(request)
    platforms = {}
    for adapter in st.registry.all():
        tab = st.hub.tab_states.get(adapter.id)
        platforms[adapter.id] = {
            "name": adapter.name,
            "logged_in": None if tab is None else tab["logged_in"],
            "tabs": [] if tab is None else tab["tab_ids"],
            "recording": adapter.id in st.hub.recording,
            "login_url": adapter.login_url or adapter.home_url,
            "login_hint": adapter.login_hint,
        }
    return ok(
        {
            "backend_version": __version__,
            "extension": st.hub.status(),
            "platforms": platforms,
            "queues": st.tasks.status(),
        }
    )
