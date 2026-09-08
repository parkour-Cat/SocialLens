"""Endpoints used only by the extension. All require the shared token header."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from .deps import ok, state

router = APIRouter(prefix="/internal", tags=["internal"])
log = get_logger("api.internal")


def _check_token(request: Request, token: str | None) -> None:
    if token != state(request).token:
        raise SocialLensError(ErrorCode.BAD_REQUEST, "invalid token")


@router.post("/upload")
async def upload(
    request: Request,
    x_sociallens_token: str | None = Header(default=None),
    x_task_id: str | None = Header(default=None),
    x_seq: int = Header(default=0),
    x_filename: str | None = Header(default=None),
):
    """Large payloads (>1 MB) and download chunks bypass the WebSocket and land here."""
    _check_token(request, x_sociallens_token)
    if not x_task_id:
        raise SocialLensError(ErrorCode.BAD_REQUEST, "X-Task-Id header required")
    st = state(request)
    body = await request.body()
    task_dir = st.settings.uploads_dir / x_task_id.replace("/", "_")
    task_dir.mkdir(parents=True, exist_ok=True)
    name = x_filename or f"{x_seq:06d}.bin"
    path = task_dir / name.replace("/", "_")
    path.write_bytes(body)
    log.info("upload stored", task_id=x_task_id, seq=x_seq, bytes=len(body))
    return ok({"path": str(path), "bytes": len(body)})
