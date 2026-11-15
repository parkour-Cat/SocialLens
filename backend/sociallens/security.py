"""Keep the local API local: only this machine's own clients may drive it.

The API runs tasks inside the user's logged-in tabs (`/run` can even `fetch` any URL with the
site's cookies), so a web page must never reach it. Binding to 127.0.0.1 is not enough:

- DNS rebinding: evil.example re-resolves to 127.0.0.1, the browser treats the API as
  same-origin with the attacker's page and lets it read responses. The Host header still says
  evil.example, so only Host values naming this machine are accepted.
- Cross-site requests: any page can fire `<img src=http://127.0.0.1:17800/api/...>` or a form
  POST. Responses stay unreadable, but the task still runs on the user's account. Browser
  requests carry Origin and/or Sec-Fetch-Site; under /api only the console itself (same
  origin) and the extension are let through. Clients outside a browser (curl, MCP, scripts)
  send neither header and are unaffected.

The WebSocket keeps its own Origin / token check in ws/hub.py; here it only gets the Host check.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
GUARDED_PREFIXES = ("/api/",)
CROSS_SITE = frozenset({"cross-site", "same-site"})


def host_name(host_header: str) -> str:
    """Hostname part of a Host header: '127.0.0.1:17800' -> '127.0.0.1', '[::1]:80' -> '::1'."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1 : h.find("]")] if "]" in h else h[1:]
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h.rstrip(".")


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: set[str], trusted_origins: set[str]):
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.trusted_origins = trusted_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "")
        if host_name(host) not in self.allowed_hosts:
            await self._reject(scope, send, f"host not allowed: {host or '(none)'}")
            return
        if scope["type"] == "http" and scope["path"].startswith(GUARDED_PREFIXES):
            reason = self._browser_check(headers, host)
            if reason:
                await self._reject(scope, send, reason)
                return
        await self.app(scope, receive, send)

    def _browser_check(self, headers: Headers, host: str) -> str | None:
        origin = headers.get("origin")
        if origin is not None:
            if origin in self.trusted_origins or origin.lower() == f"http://{host.lower()}":
                return None
            return f"cross-origin request refused: {origin}"
        site = headers.get("sec-fetch-site", "").lower()
        if site in CROSS_SITE:
            return f"cross-site request refused ({site})"
        return None

    @staticmethod
    async def _reject(scope: Scope, send: Send, message: str) -> None:
        if scope["type"] == "websocket":
            # Closing before accept makes the server answer the handshake with 403.
            await send({"type": "websocket.close", "code": 1008, "reason": message[:120]})
            return
        body: dict[str, Any] = {"success": False, "error": {"code": "forbidden", "message": message}}
        data = json.dumps(body).encode()
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())],
        })
        await send({"type": "http.response.body", "body": data})
