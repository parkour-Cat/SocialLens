"""Pseudo-platform for link diagnostics. Actions run inside the extension's service worker."""

from __future__ import annotations

from .base import Capability, PlatformAdapter, RateLimit


class SystemAdapter(PlatformAdapter):
    id = "_system"
    name = "System"
    risk_level = "low"
    rate_limit = RateLimit(interval_s=0.0, jitter_s=0.0, page_loads=0)  # 0 = no page-load budget
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip a payload through the extension", 10000),
        "cookies": Capability("cookies", "call", "Dev: cookie names/domains for params.url (no values), to pick a login marker", 10000),
    }
