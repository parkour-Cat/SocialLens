"""Task lists leave out result.items / result.raw unless full=true."""

from __future__ import annotations

from sociallens.models.task import Task, TaskStatus


def _save(db, action: str, result, created: str) -> str:
    t = Task(platform="bilibili", action=action, status=TaskStatus.DONE, result=result)
    t.created_at = t.updated_at = created
    db.save_task(t)
    return t.id


def _seed(db):
    items = [{"id": f"BV{i}", "title": "x" * 200} for i in range(30)]
    ids = {
        "collect": _save(db, "collect", {"items": items, "count": 30, "pages": 3, "limit": 30, "stopped_by": "limit"}, "2026-11-10T00:00:03+00:00"),
        "search": _save(db, "search_posts", {"items": items[:5], "cursor": "c1", "total": 99, "raw": {"big": "y" * 5000}}, "2026-11-10T00:00:02+00:00"),
        "download": _save(db, "download", {"title": "t", "files": [{"status": "done", "bytes_done": 10, "bytes_total": 10}]}, "2026-11-10T00:00:01+00:00"),
        "scalar": _save(db, "echo", None, "2026-11-10T00:00:00+00:00"),
    }
    return ids, items


def test_list_trims_items_and_raw(client, app):
    ids, _ = _seed(app.state.sl.db)
    rows = {t["id"]: t for t in client.get("/api/v1/tasks?limit=10").json()["data"]}
    c = rows[ids["collect"]]["result"]
    assert "items" not in c and c["item_count"] == 30 and c["count"] == 30 and c["pages"] == 3 and c["stopped_by"] == "limit"
    s = rows[ids["search"]]["result"]
    assert "items" not in s and "raw" not in s and s["item_count"] == 5 and s["cursor"] == "c1" and s["total"] == 99
    assert rows[ids["download"]]["result"]["files"][0]["bytes_done"] == 10  # progress kept
    assert "item_count" not in rows[ids["download"]]["result"]
    assert rows[ids["scalar"]]["result"] is None


def test_full_and_single_task_keep_everything(client, app):
    ids, items = _seed(app.state.sl.db)
    full = {t["id"]: t for t in client.get("/api/v1/tasks?limit=10&full=true").json()["data"]}
    assert full[ids["collect"]]["result"]["items"] == items
    assert full[ids["search"]]["result"]["raw"] == {"big": "y" * 5000}
    one = client.get(f"/api/v1/tasks/{ids['collect']}").json()["data"]
    assert one["result"]["items"] == items and "item_count" not in one["result"]


def test_action_filter_is_applied_before_the_limit(client, app):
    db = app.state.sl.db
    ids, _ = _seed(db)
    for i in range(5):
        _save(db, "search_posts", {"items": []}, f"2026-11-11T00:00:0{i}+00:00")  # newer, other action
    rows = client.get("/api/v1/tasks?action=collect&limit=1").json()["data"]
    assert [t["id"] for t in rows] == [ids["collect"]]
    collects = client.get("/api/v1/collects").json()["data"]
    assert [t["id"] for t in collects] == [ids["collect"]] and "items" not in collects[0]["result"]
    downloads = client.get("/api/v1/downloads").json()["data"]
    assert [t["id"] for t in downloads] == [ids["download"]]
