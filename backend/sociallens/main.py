"""FastAPI app factory. Run with `uv run sociallens` or `uv run uvicorn sociallens.asgi:app`."""

from __future__ import annotations

from pathlib import Path

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router as api_router
from .api.deps import fail
from .app_state import AppState
from .collect import CollectManager
from .download import DownloadManager
from .config import Settings, get_settings
from .logging_setup import get_logger, setup_logging
from .models.errors import ErrorCode, SocialLensError
from .platforms.registry import build_registry
from .storage.db import Database
from .storage.raw import RawStore
from .tasks.manager import TaskManager
from .ws.hub import ExtensionHub

log = get_logger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    setup_logging(settings.log_level, settings.logs_dir)
    token = settings.load_or_create_token()

    registry = build_registry()
    db = Database(settings.db_path)
    raw = RawStore(settings.raw_dir)
    hub = ExtensionHub(token, settings.ws_heartbeat_s, settings.ws_auth_timeout_s, __version__, settings.allowed_origins)
    tasks = TaskManager(hub, registry, db, settings.task_timeout_s, settings.pause_on_rate_limit_s)
    downloads = DownloadManager(settings.downloads_dir, registry, tasks, proxy=settings.download_proxy)
    collects = CollectManager(registry, tasks, db)

    async def on_capture(msg: dict[str, Any]) -> None:
        platform = msg.get("platform") or "unknown"
        if platform in hub.recording:
            path = raw.save(platform, msg)
            log.debug("capture saved", platform=platform, path=str(path))

    hub.capture_handler = on_capture

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await tasks.start()
        log.info(
            "sociallens backend started",
            version=__version__,
            url=f"http://{settings.host}:{settings.port}",
            data_dir=str(settings.data_dir),
            token_file=str(settings.token_path),
        )
        print(f"\n  SocialLens backend   http://{settings.host}:{settings.port}")
        print(f"  extension id         {settings.extension_id}  (connects automatically, no token needed)")
        print(f"  fallback token       {token}")
        print(f"  data dir             {settings.data_dir}\n", flush=True)
        try:
            yield
        finally:
            await tasks.stop()
            db.close()

    app = FastAPI(title="SocialLens", version=__version__, lifespan=lifespan)
    app.state.sl = AppState(settings, token, registry, db, raw, hub, tasks, downloads, collects)

    @app.exception_handler(SocialLensError)
    async def _sl_error(_: Request, exc: SocialLensError):
        return JSONResponse(status_code=exc.http_status, content=fail(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("unhandled error", error=repr(exc))
        return JSONResponse(status_code=500, content=fail(SocialLensError(ErrorCode.INTERNAL, repr(exc))))

    @app.get("/health")
    async def health():
        """Liveness: {status, version}."""
        return {"status": "ok", "version": __version__}

    app.include_router(api_router)

    # local web UI: static single page under /ui (sociallens/ui/), "/" redirects there
    ui_dir = Path(__file__).parent / "ui"
    app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/ui/")

    @app.websocket("/ws/extension")
    async def ws_extension(ws: WebSocket):
        await hub.handle(ws)

    return app


def run() -> None:
    s = get_settings()
    uvicorn.run("sociallens.asgi:app", host=s.host, port=s.port, log_level=s.log_level.lower())


if __name__ == "__main__":
    run()
