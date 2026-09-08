"""Local web UI is served from the package; cache browse routes back it."""

from __future__ import annotations


def test_ui_served(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308) and r.headers["location"].rstrip("/") == "/ui"
    r = client.get("/ui/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "SocialLens" in r.text and "/api/v1" in r.text


def test_items_routes(client, app):
    db = app.state.sl.db
    assert client.get("/api/v1/items?kind=posts").json()["data"] == []
    db.upsert_items("posts", "bilibili", [{"id": "BV1", "platform": "bilibili", "title": "t"}, {"id": "BV2", "platform": "bilibili", "title": "u"}])
    db.upsert_items("users", "x", [{"id": "nasa", "platform": "x", "name": "NASA"}])
    posts = client.get("/api/v1/items?kind=posts&platform=bilibili").json()["data"]
    assert {p["id"] for p in posts} == {"BV1", "BV2"}
    assert client.get("/api/v1/items?kind=users").json()["data"][0]["id"] == "nasa"
    assert client.get("/api/v1/items?kind=posts&platform=x").json()["data"] == []
    assert client.get("/api/v1/items/posts/bilibili/BV1").json()["data"]["title"] == "t"
    assert client.get("/api/v1/items/posts/bilibili/nope").status_code == 404
    assert client.get("/api/v1/items?kind=bogus").status_code == 422


def test_mcp_tools_listing(client):
    d = client.get("/api/v1/mcp/tools").json()["data"]
    names = {t["name"] for t in d["tools"]}
    assert {"search", "get_post", "collect", "download", "get_replies"} <= names
    assert all(t["description"] and "properties" in t["input_schema"] for t in d["tools"])
    assert any(r["uri"] == "sociallens://platforms" for r in d["resources"]) and d["resource_templates"]
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/{platform}/collect" in paths and "/api/v1/resolve" in paths
