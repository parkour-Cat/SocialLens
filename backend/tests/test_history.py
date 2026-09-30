"""Query history, metric snapshots and the Chrome-stuck diagnosis."""

from __future__ import annotations

from sociallens.known_issues import KNOWN_ISSUES
from sociallens.tasks.manager import diagnose


def test_snapshots_only_on_change(app):
    db = app.state.sl.db
    post = {"id": "BV1", "platform": "bilibili", "title": "t", "metrics": {"likes": 10, "comments": 1, "views": None}}
    db.upsert_items("posts", "bilibili", [post])
    db.upsert_items("posts", "bilibili", [post])  # same numbers: no new snapshot
    db.upsert_items("posts", "bilibili", [{**post, "metrics": {"likes": 12, "comments": 1}}])
    db.upsert_items("posts", "bilibili", [{"id": "BV2", "platform": "bilibili"}])  # no metrics: nothing
    h = db.item_history("posts", "bilibili", "BV1")
    assert [s["metrics"] for s in h] == [{"likes": 10, "comments": 1}, {"likes": 12, "comments": 1}]
    assert db.item_history("posts", "bilibili", "BV2") == []


def test_query_history_roundtrip(client, app):
    db = app.state.sl.db
    items = [{"id": "a", "platform": "x", "content": "one", "metrics": {"likes": 1}}, {"id": "b", "platform": "x", "content": "two", "metrics": {"likes": 2}}]
    db.upsert_items("posts", "x", items)
    qid = db.save_query("x", "search_posts", {"keyword": "AI agent", "cursor": None, "_instance": "ext1"}, "posts", items, task_id="t1")
    db.save_query("x", "search_posts", {"keyword": "AI agent", "cursor": "c2"}, "posts", items[:1], first_page=False)
    db.save_query("youtube", "get_comments", {"post_id": "v1"}, "comments", [{"id": "c1"}], source="collect")
    db.upsert_items("posts", "x", [{**items[0], "metrics": {"likes": 99}}])  # 'a' grew after the query

    rows = client.get("/api/v1/queries").json()["data"]
    assert [r["key"] for r in rows] == ["v1", "AI agent"] and rows[1]["count"] == 2 and rows[1]["source"] == "api" and rows[1]["params"] == {"keyword": "AI agent"}
    assert len(client.get("/api/v1/queries?all_pages=true").json()["data"]) == 3
    assert [r["platform"] for r in client.get("/api/v1/queries?platform=youtube").json()["data"]] == ["youtube"]
    assert [r["id"] for r in client.get("/api/v1/queries?q=agent").json()["data"]] == [qid]
    q = client.get(f"/api/v1/queries/{qid}").json()["data"]
    assert [i["id"] for i in q["items"]] == ["a", "b"]
    assert q["items"][0]["metrics"] == {"likes": 99} and q["items"][0]["metrics_then"] == {"likes": 1}
    assert client.get("/api/v1/queries/999").status_code == 404
    h = client.get("/api/v1/items/posts/x/a/history").json()["data"]
    assert [s["metrics"]["likes"] for s in h["snapshots"]] == [1, 99]
    assert client.get("/api/v1/items/bogus/x/a/history").status_code == 400


def test_known_issues_and_diagnosis(client):
    d = client.get("/api/v1/known-issues").json()["data"]
    assert d and all({"id", "platform", "status", "title", "title_en", "detail", "detail_en", "since"} <= set(i) for i in d)
    assert {i["status"] for i in d} <= {"open", "unverified", "limit", "by_design"}
    assert len({i["id"] for i in KNOWN_ISSUES}) == len(KNOWN_ISSUES)
    assert all(i["platform"] == "extension" for i in client.get("/api/v1/known-issues?platform=extension").json()["data"])
    hit = [{"at": "2026-09-29T10:00:00+00:00", "task_id": "t1", "platform": "douyin", "action": "search_posts"}, {"at": "2026-09-29T10:01:00+00:00", "task_id": "t2", "platform": "x", "action": "get_feed"}]
    assert diagnose(hit, online=True)["chrome_stuck"] == {"since": "2026-09-29T10:00:00+00:00", "tasks": 2, "platforms": ["douyin", "x"], "hint": diagnose(hit, True)["chrome_stuck"]["hint"], "hint_en": diagnose(hit, True)["chrome_stuck"]["hint_en"]}
    assert diagnose(hit[:1], online=True) is None  # one timeout can be the site
    assert diagnose(hit, online=False) is None  # offline extension is its own alert
    assert client.get("/api/v1/status").json()["data"]["diagnosis"] is None
