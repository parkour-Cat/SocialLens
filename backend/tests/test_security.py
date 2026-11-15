"""The local API answers only this machine's own clients (see sociallens/security.py)."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from sociallens.config import Settings
from sociallens.security import host_name

EXT_ORIGIN = f"chrome-extension://{Settings().extension_id}"


@pytest.mark.parametrize(
    "header,name",
    [("127.0.0.1:17800", "127.0.0.1"), ("LOCALHOST", "localhost"), ("[::1]:17800", "::1"), ("::1", "::1"), ("localhost.", "localhost"), ("", "")],
)
def test_host_name(header, name):
    assert host_name(header) == name


@pytest.mark.parametrize("host", ["127.0.0.1:17800", "localhost:17800", "[::1]:17800", "testserver"])
def test_loopback_hosts_allowed(client, host):
    assert client.get("/api/v1/status", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/status", "/ui/", "/health", "/docs"])
def test_rebound_host_refused(client, path):
    # DNS rebinding: the page's own hostname now resolves to 127.0.0.1
    r = client.get(path, headers={"host": "evil.example:17800"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_rebound_host_refused_on_websocket(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/extension", headers={"host": "evil.example", "origin": EXT_ORIGIN}) as ws:
            ws.receive_json()


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://127.0.0.1:9999"])
def test_cross_origin_api_refused(client, origin):
    r = client.post("/api/v1/tasks/echo", json={}, headers={"origin": origin})
    assert r.status_code == 403
    r = client.get("/api/v1/bilibili/search?keyword=x", headers={"origin": origin})
    assert r.status_code == 403


def test_run_refused_cross_origin(client):
    r = client.post("/api/v1/bilibili/run", json={"action": "fetch", "params": {"url": "https://api.bilibili.com/x"}}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_without_origin_refused(client, site):
    # <img src=...> / top-level link to an API URL: no Origin header, but Sec-Fetch-Site tells
    r = client.get("/api/v1/bilibili/search?keyword=x", headers={"sec-fetch-site": site})
    assert r.status_code == 403


def test_console_same_origin_allowed(client):
    r = client.post("/api/v1/tasks/echo", json={}, headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"})
    assert r.status_code == 503  # reached the handler: extension offline
    r = client.get("/api/v1/status", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code == 200


def test_extension_origin_allowed(client):
    r = client.post("/api/v1/bilibili/resume", headers={"origin": EXT_ORIGIN, "sec-fetch-site": "none"})
    assert r.status_code == 200


def test_non_browser_clients_allowed(client):
    # curl / MCP / scripts: no Origin, no Sec-Fetch-Site
    assert client.get("/api/v1/status").status_code == 200


def test_cross_site_link_to_console_allowed(client):
    # following a link to the console is fine; only /api is guarded against browsers
    r = client.get("/ui/", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 200


def test_allowed_hosts_setting():
    s = Settings(host="0.0.0.0", allowed_hosts="sociallens.lan, Box.local")
    assert {"127.0.0.1", "localhost", "::1", "sociallens.lan", "box.local"} == s.allowed_host_names
    assert "192.168.1.5" in Settings(host="192.168.1.5").allowed_host_names
