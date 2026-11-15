"""Disk usage and retention (sociallens/storage/retention.py, /api/v1/storage)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from sociallens.models.task import Task, TaskStatus


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")


def _task(db, status: TaskStatus, days_ago: float) -> str:
    t = Task(platform="bilibili", action="search_posts", status=status, result={"items": ["x" * 100]})
    t.created_at = t.updated_at = _ago(days_ago)
    db.save_task(t)
    return t.id


def _old_file(path, days_ago: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 10)
    ts = time.time() - days_ago * 86400
    os.utime(path, (ts, ts))


def test_usage_reports_tables_dirs_and_policy(client, app):
    db = app.state.sl.db
    _task(db, TaskStatus.DONE, 1)
    db.upsert_items("posts", "bilibili", [{"id": "BV1", "metrics": {"views": 1}}])
    body = client.get("/api/v1/storage").json()["data"]
    assert body["tables"]["tasks"]["rows"] == 1 and body["tables"]["tasks"]["bytes"] > 100
    assert body["tables"]["items"]["rows"] == 1 and body["tables"]["snapshots"]["rows"] == 1
    assert set(body["dirs"]) == {"downloads", "raw", "uploads", "logs"}
    assert body["db"]["bytes"] > 0
    assert body["policy"]["tasks"] == 30 and body["policy"]["items"] == 0
    assert body["last_prune"] is None


def test_policy_prune_keeps_user_data_and_unfinished_tasks(client, app):
    st = app.state.sl
    db = st.db
    old_done = _task(db, TaskStatus.DONE, 40)
    old_failed = _task(db, TaskStatus.FAILED, 40)
    old_running = _task(db, TaskStatus.RUNNING, 40)
    new_done = _task(db, TaskStatus.DONE, 1)
    db.upsert_items("posts", "bilibili", [{"id": "BV1"}])
    db.conn.execute("UPDATE items SET updated_at=?", (_ago(400),))
    db.save_health({"platform": "bilibili", "checked_at": _ago(40), "state": "ok"})
    db.save_health({"platform": "bilibili", "checked_at": _ago(1), "state": "ok"})
    _old_file(st.settings.raw_dir / "bilibili" / "2026-01-01" / "a.json", 40)
    _old_file(st.settings.raw_dir / "bilibili" / "today" / "b.json", 0)
    _old_file(st.settings.uploads_dir / "t1" / "000000.bin", 2)

    r = client.post("/api/v1/storage/prune", json={}).json()["data"]
    assert r["removed"]["tasks"] == 2 and r["removed"]["health"] == 1
    assert r["removed"]["raw"] == 1 and r["removed"]["uploads"] == 1
    assert "items" not in r["removed"]  # retention 0 = keep forever
    assert r["vacuumed"] is True

    assert db.get_task(old_done) is None and db.get_task(old_failed) is None
    assert db.get_task(old_running) is not None and db.get_task(new_done) is not None
    assert db.get_item("posts", "bilibili", "BV1") is not None
    assert not (st.settings.raw_dir / "bilibili" / "2026-01-01").exists()  # emptied dir removed
    assert (st.settings.raw_dir / "bilibili" / "today" / "b.json").exists()
    assert client.get("/api/v1/storage").json()["data"]["last_prune"]["removed"]["tasks"] == 2


def test_explicit_targets_override_policy(client, app):
    db = app.state.sl.db
    db.upsert_items("posts", "bilibili", [{"id": "BV1", "metrics": {"views": 1}}, {"id": "BV2"}])
    _task(db, TaskStatus.DONE, 40)
    r = client.post("/api/v1/storage/prune", json={"older_than_days": {"items": 0, "snapshots": 0}, "vacuum": False}).json()["data"]
    assert r["removed"] == {"items": 2, "snapshots": 1}
    assert r["vacuumed"] is False
    assert client.get("/api/v1/storage").json()["data"]["tables"]["tasks"]["rows"] == 1  # not in this request


def test_downloads_are_never_a_target(client, app):
    f = app.state.sl.settings.downloads_dir / "bilibili" / "u" / "BV1_0.mp4"
    _old_file(f, 400)
    r = client.post("/api/v1/storage/prune", json={"older_than_days": {"downloads": 0}})
    assert r.status_code == 400 and "downloads" in r.json()["error"]["message"]
    client.post("/api/v1/storage/prune", json={})
    assert f.exists()


def test_bad_days_rejected(client):
    r = client.post("/api/v1/storage/prune", json={"older_than_days": {"tasks": -1}})
    assert r.status_code == 400


def test_log_file_rotates(settings, tmp_path):
    import logging

    from sociallens.logging_setup import setup_logging

    logs = tmp_path / "logs"
    setup_logging("INFO", logs, max_mb=0.001, backups=2)  # ~1 KB
    lg = logging.getLogger("rot")
    for i in range(200):
        lg.info("line %d %s", i, "x" * 50)
    names = sorted(p.name for p in logs.iterdir())
    assert names == ["backend.log", "backend.log.1", "backend.log.2"]
    assert (logs / "backend.log").stat().st_size < 2048
