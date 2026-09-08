def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_offline(client):
    r = client.get("/api/v1/status")
    body = r.json()
    assert body["success"] is True
    assert body["data"]["extension"]["online"] is False
    assert "bilibili" in body["data"]["platforms"]
    assert "_system" not in body["data"]["platforms"]


def test_platforms_and_capabilities(client):
    r = client.get("/api/v1/platforms")
    ids = [p["id"] for p in r.json()["data"]]
    assert ids == ["bilibili", "xiaohongshu", "douyin", "weixin_mp", "kuaishou", "weixin_channels", "youtube", "x", "reddit", "zhihu", "tiktok", "instagram", "linkedin", "toutiao"]

    r = client.get("/api/v1/bilibili/capabilities")
    assert r.status_code == 200
    actions = [c["action"] for c in r.json()["data"]["capabilities"]]
    assert "echo" in actions

    r = client.get("/api/v1/nope/capabilities")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_platform"


def test_echo_requires_extension(client):
    r = client.post("/api/v1/tasks/echo", json={"payload": {"a": 1}})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "extension_offline"


def test_upload_requires_token(client, token, settings):
    r = client.post("/api/v1/internal/upload", content=b"x", headers={"X-Task-Id": "t1"})
    assert r.status_code == 400
    r = client.post(
        "/api/v1/internal/upload",
        content=b"hello",
        headers={"X-Task-Id": "t1", "X-SocialLens-Token": token, "X-Seq": "3"},
    )
    assert r.status_code == 200
    assert (settings.uploads_dir / "t1" / "000003.bin").read_bytes() == b"hello"
