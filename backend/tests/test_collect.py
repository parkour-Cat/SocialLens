"""Multi-page collect tasks driven through the fake extension with the bilibili search fixture."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sociallens.platforms.bilibili import parsers as bp
from test_extension_link import _auth, _next_dispatch, _open

FIX = Path(__file__).parent / "fixtures"


def _fixture(platform: str, name: str):
    path = FIX / platform / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {platform}/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_done(client, task_id: str, timeout_s: float = 20) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        t = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
        if t["status"] in ("done", "failed", "cancelled"):
            return t
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} still running")


def _page_with_items(raw: dict, ids_prefix: str) -> dict:
    """The fixture page again, with ids rewritten so a later page looks like new items."""
    page = json.loads(json.dumps(raw))
    for i, item in enumerate(page["data"]["result"]):
        item["bvid"] = f"{ids_prefix}{i}"
    return page


def test_collect_stops_at_limit_and_dedupes(client):
    raw = _fixture("bilibili", "search_posts")
    n_page = len(bp.parse_search_posts(raw)["items"])  # the parser skips non-video rows
    with _open(client) as ws:
        _auth(ws, actions={"bilibili": ["search_posts"]})
        r = client.post("/api/v1/bilibili/collect", json={"action": "search_posts", "params": {"keyword": "露营"}, "limit": n_page + 5})
        assert r.status_code == 200, r.text
        task = r.json()["data"]
        assert task["action"] == "collect"
        m1 = _next_dispatch(ws)
        assert m1["action"] == "search_posts" and "cursor" not in m1["params"] and m1["params"]["keyword"] == "露营"
        ws.send_json({"type": "task.result", "id": m1["id"], "ok": True, "payload": raw})
        m2 = _next_dispatch(ws)  # page 2: the cursor decoded into page=2
        assert m2["params"].get("page") == 2
        ws.send_json({"type": "task.result", "id": m2["id"], "ok": True, "payload": _page_with_items(raw, "BVnew")})
        done = _wait_done(client, task["id"])
    res = done["result"]
    assert done["status"] == "done" and res["stopped_by"] == "limit" and res["pages"] == 2
    assert res["count"] == n_page + 5 == len(res["items"]) and len({i["id"] for i in res["items"]}) == res["count"]
    assert client.get("/api/v1/items?kind=posts&platform=bilibili&limit=500").json()["data"]
    listed = client.get("/api/v1/tasks?action=collect").json()["data"]
    assert listed and listed[0]["id"] == task["id"]


def test_collect_ends_when_site_has_no_more(client):
    raw = _fixture("bilibili", "search_posts")
    with _open(client) as ws:
        _auth(ws, actions={"bilibili": ["search_posts"]})
        r = client.post("/api/v1/bilibili/collect", json={"action": "search_posts", "params": {"keyword": "x"}, "limit": 1000, "max_pages": 5})
        task = r.json()["data"]
        m1 = _next_dispatch(ws)
        ws.send_json({"type": "task.result", "id": m1["id"], "ok": True, "payload": raw})
        m2 = _next_dispatch(ws)
        empty = json.loads(json.dumps(raw))
        empty["data"]["result"] = []
        ws.send_json({"type": "task.result", "id": m2["id"], "ok": True, "payload": empty})
        done = _wait_done(client, task["id"])
    res = done["result"]
    assert done["status"] == "done" and res["complete"] is True and res["stopped_by"] == "no_more" and res["pages"] == 2
    assert res["count"] == len(bp.parse_search_posts(raw)["items"])


def test_collect_keeps_pages_before_an_error(client):
    raw = _fixture("bilibili", "search_posts")
    with _open(client) as ws:
        _auth(ws, actions={"bilibili": ["search_posts"]})
        r = client.post("/api/v1/bilibili/collect", json={"action": "search_posts", "params": {"keyword": "x"}, "limit": 1000})
        task = r.json()["data"]
        m1 = _next_dispatch(ws)
        ws.send_json({"type": "task.result", "id": m1["id"], "ok": True, "payload": raw})
        m2 = _next_dispatch(ws)
        ws.send_json({"type": "task.result", "id": m2["id"], "ok": False, "error": {"code": "captcha_required", "message": "slider"}})
        done = _wait_done(client, task["id"])
    res = done["result"]
    assert done["status"] == "done" and res["stopped_by"] == "error" and res["error"]["code"] == "captcha_required"
    assert res["count"] == len(bp.parse_search_posts(raw)["items"]) and res["pages"] == 1


def test_collect_rejects_non_list_actions(client):
    r = client.post("/api/v1/bilibili/collect", json={"action": "get_post", "params": {"id": "BV1"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    r = client.post("/api/v1/nope/collect", json={"action": "search_posts", "params": {}})
    assert r.status_code == 404
