"""GET /search fans one keyword out to several platforms; each entry stands on its own."""

from __future__ import annotations


def test_search_all_isolates_platforms(client):
    r = client.get("/api/v1/search?keyword=x&platforms=bilibili,linkedin,bilibili")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["keyword"] == "x" and d["type"] == "post"
    assert [e["platform"] for e in d["results"]] == ["bilibili", "linkedin"]  # deduplicated, order kept
    by = {e["platform"]: e for e in d["results"]}
    assert by["bilibili"]["error"]["code"] == "extension_offline" and by["bilibili"]["items"] == []
    assert by["linkedin"]["error"]["code"] == "unsupported"  # no search_posts there
    q = by["bilibili"]["quota"]
    assert q["page_loads"] == 40 and q["window_s"] == 600 and q["page_loads_used"] == 0
    assert client.get("/api/v1/search?keyword=x&platforms=bilibili&type=user").json()["data"]["type"] == "user"


def test_search_all_rejects_bad_input(client):
    assert client.get("/api/v1/search?keyword=x&platforms=bilibili,bogus").status_code == 404
    assert client.get("/api/v1/search?keyword=x&platforms=").status_code == 422
    assert client.get("/api/v1/search?keyword=&platforms=bilibili").status_code == 422
    assert client.get("/api/v1/search?keyword=x&platforms=bilibili&type=video").status_code == 422
