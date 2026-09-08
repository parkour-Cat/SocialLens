"""Backend half of a platform adapter.

The extension half (URL matching, login detection, how to execute an action) lives in
extension/src/platforms/<platform>/. This side declares capabilities and turns raw
responses into unified models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Strategy = Literal["call", "navigate"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RateLimit:
    """interval_s/jitter_s space out every dispatch. page_loads caps how many *new page loads*
    (navigate tasks without a cursor, i.e. a fresh tab visiting a URL) may start within window_s;
    in-tab calls and scroll pagination are not counted. Over budget, tasks wait in the queue."""

    interval_s: float = 2.0
    jitter_s: float = 1.0
    page_loads: int = 40
    window_s: float = 600.0


@dataclass(frozen=True)
class Capability:
    action: str
    strategy: Strategy = "call"
    description: str = ""
    timeout_ms: int = 30000


class PlatformAdapter:
    id: str = ""
    name: str = ""
    home_url: str = ""
    login_url: str = ""
    login_hint: str = ""
    domains: tuple[str, ...] = ()
    risk_level: RiskLevel = "medium"
    rate_limit: RateLimit = RateLimit()
    capabilities: dict[str, Capability] = {}

    def capability(self, action: str) -> Capability | None:
        return self.capabilities.get(action)

    async def prepare(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Async hook before build_params for adapters that need a lookup to build the entry URL
        (e.g. TikTok: video id -> author handle). Default: passthrough."""
        return params

    def build_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Translate REST params into what the extension action expects. Default: passthrough."""
        return params

    def parse(self, action: str, raw: Any) -> Any:
        """Turn the extension's raw payload into unified models. Default: passthrough."""
        return raw

    async def download_sources(self, post: dict[str, Any], run: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Downloadable sources of a parsed post (see download/__init__.py for the dict shape).

        Default: every MediaItem with a direct URL. `run(action, params)` executes another action of
        this platform through the extension, for platforms whose stream URLs need a second call.
        Items flagged encrypted / needs_playurl / needs_stream_resolution are skipped here and
        handled by the platform's override.
        """
        out: list[dict[str, Any]] = []
        for i, m in enumerate(post.get("media") or []):
            if not isinstance(m, dict) or not m.get("url") or m.get("encrypted"):
                continue
            extra = m.get("extra") or {}
            if extra.get("needs_playurl") or extra.get("needs_stream_resolution"):
                continue
            out.append({"index": i, "type": m.get("type"), "url": m["url"], "headers": m.get("headers") or {}, "backup_urls": extra.get("backup_urls") or []})
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "home_url": self.home_url,
            "login_url": self.login_url or self.home_url,
            "login_hint": self.login_hint,
            "domains": list(self.domains),
            "risk_level": self.risk_level,
            "rate_limit": {
                "interval_s": self.rate_limit.interval_s,
                "jitter_s": self.rate_limit.jitter_s,
                "page_loads": self.rate_limit.page_loads,
                "window_s": self.rate_limit.window_s,
            },
            "capabilities": [
                {
                    "action": c.action,
                    "strategy": c.strategy,
                    "description": c.description,
                    "timeout_ms": c.timeout_ms,
                }
                for c in self.capabilities.values()
            ],
        }
