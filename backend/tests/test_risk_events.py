"""Risk-control hits are logged with the traffic that preceded them (evidence, not behaviour)."""

from __future__ import annotations

from sociallens.models.errors import ErrorCode, SocialLensError
from sociallens.models.task import Task


def test_queue_evidence_and_recording(client, app):
    st = app.state.sl
    tasks = st.tasks
    q = tasks._ensure_queue("xiaohongshu")
    for action, page in [("search_posts", True), ("search_posts", False), ("get_comments", True), ("search_users", True)]:
        q.note_dispatch(action, page)
    tasks.note_context("xiaohongshu", "multi_search")
    ev = q.evidence()
    assert ev["page_loads_10m"] == 3 and ev["tasks_10m"] == 4 and ev["actions_60m"] == {"search_posts": 2, "get_comments": 1, "search_users": 1}
    assert ev["contexts_10m"] == ["multi_search"] and ev["since_last_hit_s"] is None and ev["min_gap_s_10m"] is not None

    task = Task(platform="xiaohongshu", action="search_posts", params={"url": "https://www.xiaohongshu.com/search_result?keyword=x"}, strategy="navigate")
    rec = tasks.record_risk(task, q, SocialLensError(ErrorCode.RATE_LIMITED, "search.state == error"))
    assert rec["platform"] == "xiaohongshu" and rec["code"] == "rate_limited" and rec["page_load"] is True and rec["hits_24h"] == 0
    assert q.evidence()["hits_24h"] == 1 and q.evidence()["since_last_hit_s"] == 0

    d = client.get("/api/v1/risk/events").json()["data"]
    assert len(d["events"]) == 1 and d["events"][0]["task_id"] == task.id and d["events"][0]["contexts_10m"] == ["multi_search"]
    assert d["summary"]["xiaohongshu"] == {"count": 1, "last_at": rec["at"], "last_code": "rate_limited"}
    assert client.get("/api/v1/risk/events?platform=bilibili").json()["data"]["events"] == []
    assert st.db.risk_events("xiaohongshu")[0]["code"] == "rate_limited"


def test_other_failures_are_not_risk_events(client, app):
    # without an extension every data call fails with extension_offline: not a risk-control signal
    assert client.get("/api/v1/bilibili/search?keyword=x").status_code == 503
    assert client.get("/api/v1/risk/events").json()["data"]["events"] == []
