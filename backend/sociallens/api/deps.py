from __future__ import annotations

from typing import Any

from fastapi import Request

from ..app_state import AppState
from ..models.errors import SocialLensError


def state(request: Request) -> AppState:
    return request.app.state.sl


def ok(data: Any, platform: str | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True}
    if platform:
        body["platform"] = platform
    body["data"] = data
    body.update(extra)
    return body


def fail(err: SocialLensError) -> dict[str, Any]:
    return {"success": False, "error": err.to_dict()}
