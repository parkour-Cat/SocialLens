"""Runtime configuration. All values can be overridden with SOCIALLENS_* env vars."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOCIALLENS_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 17800
    data_dir: Path = REPO_DIR / "data"
    # Proxy for backend downloads and yt-dlp. "system" (default) mirrors what the browser uses:
    # HTTPS_PROXY/HTTP_PROXY env, else the Windows/macOS system proxy. "off" disables, or give a URL.
    download_proxy: str = "system"
    log_level: str = "INFO"

    # Task defaults
    task_timeout_s: float = 30.0
    default_rate_interval_s: float = 2.0
    pause_on_rate_limit_s: float = 300.0

    # Extension link. The extension's ID is fixed by the `key` in extension/manifest.json, so
    # the WebSocket Origin header (set by the browser, not forgeable by web pages) identifies it.
    # The token file remains as a fallback for setups where the Origin check cannot be used.
    extension_id: str = "ngpcmljglingphokjangbhkalkjiddbi"
    extra_extension_ids: str = ""  # comma separated, e.g. a dev build with a different ID
    ws_heartbeat_s: float = 20.0
    ws_auth_timeout_s: float = 5.0

    @property
    def allowed_origins(self) -> set[str]:
        ids = [self.extension_id, *[x.strip() for x in self.extra_extension_ids.split(",")]]
        return {f"chrome-extension://{i}" for i in ids if i}

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sociallens.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.downloads_dir, self.uploads_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def load_or_create_token(self) -> str:
        self.ensure_dirs()
        if self.token_path.exists():
            token = self.token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_urlsafe(32)
        self.token_path.write_text(token, encoding="utf-8")
        return token


@lru_cache
def get_settings() -> Settings:
    return Settings()
