"""Download pipeline: fake extension answers get_post with a recorded fixture, media is served by
an httpx MockTransport, files land under data/downloads/{platform}/{author}/."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from sociallens.platforms.bilibili import parsers as bp
from sociallens.platforms.youtube import parsers as yp

from test_extension_link import _auth, _next_dispatch, _open

FIX = Path(__file__).parent / "fixtures"


def _fixture(platform: str, name: str):
    path = FIX / platform / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {platform}/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _mock_media(app, body: bytes = b"\x00" * 1000, content_type: str = "video/mp4"):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers.get("user-agent", "").startswith("Mozilla/5.0")
        return httpx.Response(200, content=body, headers={"content-type": content_type, "content-length": str(len(body))})

    app.state.sl.downloads.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return calls


def _wait_done(client, task_id: str, timeout_s: float = 15) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        t = client.get(f"/api/v1/tasks/{task_id}").json()["data"]
        if t["status"] in ("done", "failed", "cancelled"):
            return t
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} still running")


def test_download_x_post(client, app, settings):
    raw = _fixture("douyin", "get_post")
    calls = _mock_media(app)
    with _open(client) as ws:
        _auth(ws, actions={"douyin": ["get_post"]})
        ws.send_json({"type": "tab.state", "platform": "douyin", "logged_in": True, "tab_ids": [1]})
        r = client.post("/api/v1/douyin/posts/any/download", json={})
        assert r.status_code == 200, r.text
        task = r.json()["data"]
        assert task["action"] == "download" and task["status"] in ("queued", "running")

        msg = _next_dispatch(ws)
        assert msg["action"] == "get_post" and msg["platform"] == "douyin"
        ws.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": raw})

        done = _wait_done(client, task["id"])
    assert done["status"] == "done", done
    files = done["result"]["files"]
    assert files and all(f["status"] == "done" for f in files)
    assert len(calls) == len(files)
    for f in files:
        p = Path(f["path"])
        assert p.exists() and p.stat().st_size == 1000 and p.suffix == ".mp4"
        assert p.parent.parent.parent == settings.downloads_dir
        assert p.parent.parent.name == "douyin"
    listed = client.get("/api/v1/downloads?platform=douyin").json()["data"]
    assert listed and listed[0]["id"] == task["id"]


def test_download_media_index_and_unknown(client, app):
    raw = _fixture("douyin", "get_post")
    _mock_media(app, content_type="image/jpeg")
    with _open(client) as ws:
        _auth(ws, actions={"douyin": ["get_post"]})
        ws.send_json({"type": "tab.state", "platform": "douyin", "logged_in": True, "tab_ids": [1]})
        r = client.post("/api/v1/douyin/posts/any/download", json={"media_index": 99})
        msg = _next_dispatch(ws)
        ws.send_json({"type": "task.result", "id": msg["id"], "ok": True, "payload": raw})
        done = _wait_done(client, r.json()["data"]["id"])
    assert done["status"] == "failed" and done["error"]["code"] == "not_found"

    r = client.post("/api/v1/nope/posts/1/download", json={})
    assert r.status_code == 404


def test_download_without_extension(client):
    r = client.post("/api/v1/x/posts/1/download", json={"wait": True, "wait_s": 5})
    assert r.status_code == 200
    t = r.json()["data"]
    assert t["status"] == "failed" and t["error"]["code"] == "extension_offline"


def test_bilibili_pick_play_source():
    dash = {
        "dash": {
            "video": [
                {"id": 80, "codecid": 12, "bandwidth": 900, "baseUrl": "https://cdn/v80hevc.m4s", "width": 1920, "height": 1080},
                {"id": 80, "codecid": 7, "bandwidth": 1000, "baseUrl": "https://cdn/v80avc.m4s", "backupUrl": ["https://cdn2/v80avc.m4s"], "width": 1920, "height": 1080},
                {"id": 64, "codecid": 7, "bandwidth": 500, "baseUrl": "https://cdn/v64.m4s"},
            ],
            "audio": [{"id": 30216, "bandwidth": 60000, "baseUrl": "https://cdn/a_low.m4s"}, {"id": 30280, "bandwidth": 190000, "base_url": "https://cdn/a_high.m4s"}],
        }
    }
    src = bp.pick_play_source(dash, "dash")
    assert src["parts"][0]["url"] == "https://cdn/v80avc.m4s" and src["parts"][0]["backup_urls"] == ["https://cdn2/v80avc.m4s"]
    assert src["parts"][1]["url"] == "https://cdn/a_high.m4s" and src["ext"] == "mp4" and src["height"] == 1080
    durl = {"quality": 80, "durl": [{"url": "https://cdn/full.mp4", "backup_url": ["https://cdn2/full.mp4"]}]}
    src = bp.pick_play_source(durl, "mp4")
    assert src["url"] == "https://cdn/full.mp4" and "parts" not in src and src["segments"] == 1
    assert bp.pick_play_source(dash, "mp4") is None  # dash payload can't serve mp4 mode
    assert bp.pick_play_source({"durl": []}, "mp4") is None


def test_youtube_pick_stream_source():
    raw = _fixture("youtube", "get_post")
    srcs = yp.pick_stream_source({"streamingData": raw["player"]["streamingData"]})
    assert srcs and srcs[0]["url"].startswith("https://") and srcs[0]["ext"] == "mp4" and srcs[0]["height"]
    assert yp.pick_stream_source({"streamingData": {"formats": [{"mimeType": "video/mp4", "signatureCipher": "s=1"}]}}) == []
