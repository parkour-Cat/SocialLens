"""Comment digest: the pure builder, and GET /{platform}/posts/{id}/comments/digest end to end
through the fake extension with the (scrubbed) bilibili fixtures."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sociallens.digest import comment_digest
from sociallens.platforms.bilibili import parsers as bp
from test_extension_link import _auth, _next_dispatch, _open

FIX = Path(__file__).parent / "fixtures" / "bilibili"


def _fixture(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture bilibili/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _c(i, likes, text="hello", parent=None, day="2026-11-01", author="a", raw=None):
    return {"id": str(i), "platform": "x", "post_id": "p", "parent_id": parent, "author": {"name": author}, "content": text, "likes": likes, "publish_time": f"{day}T10:00:00+00:00", "raw": raw or {}}


def test_builder_ranks_counts_and_compacts():
    comments = [
        _c(1, 5, "first\nline   two"),
        _c(2, 100, "top", author="b", raw={"rcount": 7}),
        _c(3, 0, "", author="b"),  # sticker only: counted, not listed
        _c(4, 3, "x" * 500, parent="2", day="2026-11-02"),
        _c(2, 100, "top", author="b"),  # duplicate id across pages
    ]
    post = {"id": "p", "title": "T", "author": {"name": "up"}, "url": "u", "metrics": {"comments": 40, "likes": None, "views": 9}}
    d = comment_digest(comments, post, top_n=2)
    s = d["stats"]
    assert s["fetched"] == 4 and s["top_level"] == 3 and s["replies"] == 1 and s["without_text"] == 1
    assert s["reported_total"] == 40 and d["post"]["metrics"] == {"comments": 40, "views": 9}
    assert s["first"].startswith("2026-11-01") and s["last"].startswith("2026-11-02")
    assert s["likes"] == {"sum": 108, "max": 100, "median": 4.0, "top2_share": round(105 / 108, 3)}
    assert s["repeat_authors"] == [{"author": "a", "comments": 2}, {"author": "b", "comments": 2}]
    assert [c["likes"] for c in d["top_comments"]] == [100, 5] and [c["likes"] for c in d["others"]] == [3]
    assert d["top_comments"][0]["replies"] == 7 and d["top_comments"][0]["time"] == "2026-11-01 10:00"
    assert d["top_comments"][1]["text"] == "first line two"
    assert len(d["others"][0]["text"]) == 300 and d["others"][0]["text"].endswith("…") and d["others"][0]["reply_to"] == "2"
    assert "raw" not in json.dumps(d)


def test_relative_times_are_shown_as_given_and_not_binned():
    comments = [_c(i, i, raw={"published_text": "1 year ago"}) for i in range(5)]
    d = comment_digest(comments)
    assert d["stats"]["busiest_days"] is None and "relative" in d["stats"]["time_note"]
    assert {c["time"] for c in d["top_comments"]} == {"1 year ago"}
    assert "time_note" not in comment_digest([_c(1, 1)])["stats"]


def test_builder_handles_nothing():
    d = comment_digest([], None)
    assert d["post"] is None and d["stats"]["fetched"] == 0 and d["stats"]["likes"]["top20_share"] is None
    assert d["top_comments"] == [] and d["others"] == []


def test_builder_on_real_bilibili_comments():
    items = bp.parse_get_comments(_fixture("get_comments"))["items"]
    d = comment_digest(items, bp.parse_get_post(_fixture("get_post")))
    assert d["stats"]["fetched"] == len({c["id"] for c in items})
    assert d["top_comments"] and all(c["text"] for c in d["top_comments"])
    likes = [c["likes"] for c in d["top_comments"] + d["others"]]
    assert likes == sorted(likes, reverse=True)
    assert d["post"]["title"] and d["post"]["metrics"]["comments"] is not None


def test_endpoint_collects_and_digests(client):
    post_raw, comments_raw = _fixture("get_post"), _fixture("get_comments")
    with _open(client) as ws:
        _auth(ws, actions={"bilibili": ["get_post", "get_comments"]})
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.get, "/api/v1/bilibili/posts/BV1xx/comments/digest", params={"limit": 5})
            m = _next_dispatch(ws)
            assert m["action"] == "get_post" and m["params"]["id"] == "BV1xx"
            ws.send_json({"type": "task.result", "id": m["id"], "ok": True, "payload": post_raw})
            m = _next_dispatch(ws)
            assert m["action"] == "get_comments" and m["params"]["post_id"] == "BV1xx"
            ws.send_json({"type": "task.result", "id": m["id"], "ok": True, "payload": comments_raw})
            r = fut.result(timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["post"]["title"] and d["stats"]["fetched"] >= 5
    assert d["collect"]["stopped_by"] == "limit" and d["collect"]["status"] == "done"
    assert d["top_comments"] and "raw" not in json.dumps(d)


def test_endpoint_without_extension_reports_the_error(client):
    r = client.get("/api/v1/bilibili/posts/BV1xx/comments/digest")
    assert r.status_code == 503 and r.json()["error"]["code"] == "extension_offline"
