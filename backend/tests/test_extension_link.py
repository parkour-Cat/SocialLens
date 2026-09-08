"""Drive the backend with a fake extension over the real WebSocket protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sociallens.config import Settings

EXT_ORIGIN = f"chrome-extension://{Settings().extension_id}"


def _open(client, origin: str | None = EXT_ORIGIN):
    headers = {"origin": origin} if origin else {}
    return client.websocket_connect("/ws/extension", headers=headers)


def _auth(ws, token: str = "", version="test", actions: dict | None = None):
    ws.send_json({"type": "auth", "token": token, "extension_version": version, "actions": actions or {}})
    hello = ws.receive_json()
    assert hello["type"] == "hello"
    return ws


def _next_dispatch(ws):
    """Skip heartbeat pings that may interleave in slower tests."""
    while True:
        msg = ws.receive_json()
        if msg["type"] == "task.dispatch":
            return msg


def _expect_closed(ws):
    try:
        ws.receive_json()
        assert False, "expected close"
    except Exception:  # WebSocketDisconnect
        pass


def test_origin_alone_is_enough(client):
    with _open(client) as ws:
        _auth(ws)
        body = client.get("/api/v1/status").json()["data"]
        assert body["extension"]["auth_method"] == "origin"


def test_token_fallback_without_origin(client, token):
    with _open(client, origin="https://evil.example") as ws:
        _auth(ws, token=token)
        body = client.get("/api/v1/status").json()["data"]
        assert body["extension"]["auth_method"] == "token"


def test_unknown_origin_and_bad_token_rejected(client):
    with _open(client, origin="https://evil.example") as ws:
        ws.send_json({"type": "auth", "token": "wrong"})
        _expect_closed(ws)
    with _open(client, origin=None) as ws:
        ws.send_json({"type": "auth", "token": ""})
        _expect_closed(ws)


def test_extra_extension_ids(tmp_path):
    from fastapi.testclient import TestClient

    from sociallens.main import create_app

    s = Settings(data_dir=tmp_path / "d", extra_extension_ids="abc, def")
    with TestClient(create_app(s)) as c:
        with _open(c, origin="chrome-extension://def") as ws:
            _auth(ws)


def test_status_reflects_extension_and_tabs(client):
    with _open(client) as ws:
        _auth(ws, version="0.0.1")
        ws.send_json({"type": "tab.state", "platform": "bilibili", "logged_in": True, "tab_ids": [7]})
        ws.send_json({"type": "pong", "ts": 0})
        body = client.get("/api/v1/status").json()["data"]
        assert body["extension"]["online"] is True
        assert body["extension"]["extension_version"] == "0.0.1"
        assert body["platforms"]["bilibili"]["logged_in"] is True
        assert body["platforms"]["bilibili"]["tabs"] == [7]
    body = client.get("/api/v1/status").json()["data"]
    assert body["extension"]["online"] is False


def test_echo_round_trip(client):
    with _open(client) as ws:
        _auth(ws)
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/tasks/echo", json={"payload": {"hello": "world"}})
            msg = ws.receive_json()
            assert msg["type"] == "task.dispatch"
            assert msg["platform"] == "_system"
            assert msg["action"] == "echo"
            assert msg["params"] == {"payload": {"hello": "world"}}
            ws.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"echo": msg["params"], "via": "fake"}})
            r = fut.result(timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["data"]["via"] == "fake"
        assert body["task_id"] == msg["id"]

        r = client.get(f"/api/v1/tasks/{msg['id']}")
        assert r.json()["data"]["status"] == "done"


def test_extension_error_maps_to_http(client):
    with _open(client) as ws:
        _auth(ws)
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/echo", json={})
            msg = ws.receive_json()
            ws.send_json(
                {
                    "type": "task.result",
                    "id": msg["id"],
                    "ok": False,
                    "error": {"code": "not_logged_in", "message": "no bilibili tab"},
                }
            )
            r = fut.result(timeout=10)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "not_logged_in"


def test_generic_action_via_run(client):
    with _open(client) as ws:
        _auth(ws)
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/run", json={"action": "fetch", "params": {"url": "https://x/y"}})
            msg = ws.receive_json()
            assert msg["action"] == "fetch" and msg["strategy"] == "call"
            ws.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"status": 200}})
            r = fut.result(timeout=10)
        assert r.status_code == 200 and r.json()["data"]["status"] == 200

        r = client.post("/api/v1/bilibili/run", json={"action": "nope"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "unsupported"


def test_record_mode_saves_captures(client, settings):
    with _open(client) as ws:
        _auth(ws)
        r = client.post("/api/v1/bilibili/record", json={"enabled": True})
        assert r.status_code == 200
        assert ws.receive_json() == {"type": "record.set", "platform": "bilibili", "enabled": True}

        ws.send_json(
            {
                "type": "capture",
                "platform": "bilibili",
                "url": "https://api.bilibili.com/x/web-interface/view?bvid=BV1",
                "method": "GET",
                "status": 200,
                "body": {"code": 0, "data": {"bvid": "BV1"}},
                "ts": 1,
            }
        )
        ws.send_json({"type": "pong", "ts": 0})
        raw = client.get("/api/v1/bilibili/raw").json()["data"]
        assert len(raw) == 1
        assert "web-interface_view" in raw[0]["file"]

        client.post("/api/v1/bilibili/record", json={"enabled": False})
        assert ws.receive_json()["enabled"] is False


def test_two_instances_route_by_login(client):
    """Two extension instances: the task goes to the one logged in to the platform."""
    with _open(client) as a, _open(client) as b:
        _auth(a, version="A")
        _auth(b, version="B")
        a.send_json({"type": "tab.state", "platform": "bilibili", "logged_in": False, "tab_ids": [1]})
        b.send_json({"type": "tab.state", "platform": "bilibili", "logged_in": True, "tab_ids": []})
        a.send_json({"type": "pong", "ts": 0})
        b.send_json({"type": "pong", "ts": 0})
        st = client.get("/api/v1/status").json()["data"]
        assert len(st["extension"]["connections"]) == 2
        assert st["platforms"]["bilibili"]["logged_in"] is True
        assert st["platforms"]["bilibili"]["tabs"] == [1]

        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/echo", json={})
            msg = b.receive_json()  # routed to B (logged in)
            assert msg["type"] == "task.dispatch"
            b.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"via": "B"}})
            assert fut.result(timeout=10).json()["data"]["via"] == "B"

        # _system tasks go to the most recent instance
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/tasks/echo", json={})
            msg = b.receive_json()
            b.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"via": "B"}})
            assert fut.result(timeout=10).status_code == 200

    st = client.get("/api/v1/status").json()["data"]
    assert st["extension"]["online"] is False


def test_route_by_advertised_actions(client):
    """A stale build that lacks a platform action is skipped even if it is logged in."""
    with _open(client) as old, _open(client) as new:
        old.send_json({"type": "auth", "token": "", "extension_version": "old"})
        assert old.receive_json()["type"] == "hello"
        new.send_json({"type": "auth", "token": "", "extension_version": "new", "actions": {"bilibili": ["get_post"]}})
        assert new.receive_json()["type"] == "hello"
        old.send_json({"type": "tab.state", "platform": "bilibili", "logged_in": True, "tab_ids": [1]})
        old.send_json({"type": "pong", "ts": 0})
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/run", json={"action": "get_post", "params": {"id": "BV1"}})
            msg = new.receive_json()
            assert msg["action"] == "get_post"
            new.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"code": 0, "data": {"bvid": "BV1", "title": "t"}}})
            assert fut.result(timeout=10).status_code == 200
        # generic actions still go to the logged-in old build
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/echo", json={})
            msg = old.receive_json()
            old.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"via": "old"}})
            assert fut.result(timeout=10).json()["data"]["via"] == "old"
    with _open(client) as only_old:
        only_old.send_json({"type": "auth", "token": "", "extension_version": "old"})
        assert only_old.receive_json()["type"] == "hello"
        r = client.post("/api/v1/bilibili/run", json={"action": "get_post", "params": {"id": "BV1"}})
        assert r.status_code == 404 and "reload the extension" in r.json()["error"]["message"]


def test_instance_pin(client):
    with _open(client) as a, _open(client) as b:
        _auth(a, version="A", actions={"bilibili": ["get_post"]})
        _auth(b, version="B", actions={"bilibili": ["get_post"]})
        b.send_json({"type": "tab.state", "platform": "bilibili", "logged_in": True, "tab_ids": [2]})
        b.send_json({"type": "pong", "ts": 0})
        ids = [c["id"] for c in client.get("/api/v1/status").json()["data"]["extension"]["connections"]]
        a_id = ids[0]
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.post, "/api/v1/bilibili/echo", json={"instance": a_id})
            msg = _next_dispatch(a)  # pinned to A even though B is logged in
            a.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"via": "A"}})
            assert fut.result(timeout=10).json()["data"]["via"] == "A"
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.get, "/api/v1/bilibili/posts/BV1", headers={"x-sociallens-instance": a_id})
            msg = _next_dispatch(a)
            assert msg["params"]["_instance"] == a_id
            a.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": {"code": 0, "data": {"bvid": "BV1", "title": "t"}}})
            assert fut.result(timeout=10).status_code == 200
        r = client.post("/api/v1/bilibili/echo", json={"instance": "ext999"})
        assert r.status_code == 503


def test_page_load_budget_delays_fresh_navigations(client, app):
    """Over budget, a fresh navigate task waits for the window to slide; in-tab calls are not counted."""
    import time as _time

    from sociallens.platforms.base import RateLimit

    adapter = app.state.sl.registry.get("bilibili")
    original = adapter.rate_limit
    adapter.rate_limit = RateLimit(interval_s=0.0, jitter_s=0.0, page_loads=1, window_s=1.5)
    try:
        with _open(client) as ws:
            _auth(ws)
            with ThreadPoolExecutor(3) as pool:
                nav = {"action": "navigate", "params": {"url": "https://www.bilibili.com/", "page_action": "echo"}}
                t0 = _time.monotonic()
                f1 = pool.submit(client.post, "/api/v1/bilibili/run", json=nav)
                m1 = _next_dispatch(ws)
                ws.send_json({"type": "task.result", "id": m1["id"], "ok": True, "payload": {"n": 1}})
                f1.result(timeout=10)
                f2 = pool.submit(client.post, "/api/v1/bilibili/run", json={"action": "echo", "params": {}})
                m2 = _next_dispatch(ws)  # a call task: not a page load, dispatched at once
                assert m2["action"] == "echo"  # not a page load: dispatched without waiting for the window
                ws.send_json({"type": "task.result", "id": m2["id"], "ok": True, "payload": {"n": 2}})
                f2.result(timeout=10)
                f3 = pool.submit(client.post, "/api/v1/bilibili/run", json=nav)
                m3 = _next_dispatch(ws)  # second page load: must wait for the 1.5 s window
                waited = _time.monotonic() - t0
                assert m3["action"] == "navigate" and waited >= 1.4, waited
                ws.send_json({"type": "task.result", "id": m3["id"], "ok": True, "payload": {"n": 3}})
                f3.result(timeout=10)
        q = client.get("/api/v1/status").json()["data"]["queues"]["bilibili"]
        assert "page_loads_in_window" in q and q["budget_wait_s"] == 0
    finally:
        adapter.rate_limit = original
