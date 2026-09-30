"""Platform health probes: classification, streaks, and the routes without a browser."""

from __future__ import annotations

from sociallens.health import PROBES, classify, summarize


def test_classify_and_streaks():
    assert classify(None, 20) == "ok" and classify(None, None) == "ok"
    assert classify(None, 0) == "broken"
    assert classify({"code": "timeout"}, None) == "broken"
    assert classify({"code": "parse_error"}, None) == "broken"
    for code in ("not_logged_in", "extension_offline", "captcha_required", "rate_limited"):
        assert classify({"code": code}, None) == "blocked"
    rows = [  # newest first
        {"state": "broken", "checked_at": "2026-09-29T12:00:00+00:00"},
        {"state": "blocked", "checked_at": "2026-09-29T06:00:00+00:00"},
        {"state": "broken", "checked_at": "2026-09-29T00:00:00+00:00"},
        {"state": "ok", "checked_at": "2026-09-28T18:00:00+00:00"},
        {"state": "broken", "checked_at": "2026-09-28T12:00:00+00:00"},
    ]
    s = summarize(rows)
    assert s["state"] == "broken" and s["broken_since"] == "2026-09-29T00:00:00+00:00" and s["last_ok_at"] == "2026-09-28T18:00:00+00:00"
    s = summarize(rows[3:])
    assert s["state"] == "ok" and s["broken_since"] is None and s["last_ok_at"] == "2026-09-28T18:00:00+00:00"
    assert summarize([{"state": "broken", "checked_at": "t"}])["broken_since"] == "t"
    assert summarize([]) is None


def test_probes_match_capabilities(app):
    reg = app.state.sl.registry
    for pid, (action, _) in PROBES.items():
        assert reg.get(pid) is not None and reg.get(pid).capability(action) is not None, (pid, action)
    assert "weixin_channels" not in PROBES  # no public web surface


def test_health_routes_without_extension(client, app):
    d = client.get("/api/v1/health/platforms").json()["data"]
    assert d["interval_min"] == 360 and d["running"] is None and d["probes"]["bilibili"] == "get_trending"
    assert d["platforms"]["bilibili"] is None  # never checked
    r = client.post("/api/v1/health/check", json={"platforms": ["bilibili", "weixin_channels"]})
    assert r.status_code == 200
    t = r.json()["data"]
    assert t["action"] == "health" and t["status"] == "done"
    by = {x["platform"]: x for x in t["result"]["results"]}
    assert by["bilibili"]["state"] == "blocked" and by["bilibili"]["code"] == "extension_offline" and by["bilibili"]["action"] == "get_trending"
    assert by["weixin_channels"]["state"] == "skipped"
    d = client.get("/api/v1/health/platforms").json()["data"]
    b = d["platforms"]["bilibili"]
    assert b["state"] == "blocked" and b["broken_since"] == b["checked_at"] and b["last_ok_at"] is None
    assert client.get("/api/v1/tasks?action=health").json()["data"][0]["id"] == t["id"]
    assert client.post("/api/v1/health/check", json={"platforms": ["nope"]}).status_code == 404
    assert app.state.sl.db.health_history("bilibili")[0]["state"] == "blocked"
