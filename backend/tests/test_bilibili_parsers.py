"""Parser tests against recorded responses (scripts/sample_bilibili.py). Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili import BilibiliAdapter, parsers
from sociallens.platforms.bilibili.cursor import decode_cursor, encode_cursor

FIXTURES = Path(__file__).parent / "fixtures" / "bilibili"


def load(name: str):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name} not recorded yet (run scripts/sample_bilibili.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def test_cursor_round_trip():
    c = encode_cursor({"page": 2, "offset": "abc"})
    assert decode_cursor(c) == {"page": 2, "offset": "abc"}
    assert encode_cursor(None) is None
    assert decode_cursor("not-a-cursor") == {}


def test_search_posts():
    out = parsers.parse_search_posts(load("search_posts"))
    assert out["items"] and out["total"]
    first = out["items"][0]
    assert first["platform"] == "bilibili" and first["type"] == "video"
    assert first["id"].startswith("BV")
    assert "<em" not in (first["title"] or "")
    assert first["url"].startswith("https://www.bilibili.com/video/BV")
    assert first["cover_url"].startswith("https://")
    assert first["author"]["id"] and first["author"]["url"].startswith("https://space.bilibili.com/")
    assert first["metrics"]["views"] is not None
    assert first["publish_time"] and first["publish_time"].endswith("+00:00")
    assert decode_cursor(out["cursor"]) == {"page": 2}


def test_search_users():
    out = parsers.parse_search_users(load("search_users"))
    assert out["items"]
    u = out["items"][0]
    assert u["platform"] == "bilibili" and u["id"].isdigit()
    assert u["name"] and u["avatar_url"].startswith("https://")
    assert u["metrics"]["followers"] is not None
    assert u["url"] == f"https://space.bilibili.com/{u['id']}"


def test_get_post():
    post = parsers.parse_get_post(load("get_post"))
    assert post["id"].startswith("BV") and post["type"] == "video"
    assert post["title"] and post["author"]["name"]
    assert post["media"] and post["media"][0]["extra"]["cid"]
    assert post["media"][0]["headers"]["Referer"] == "https://www.bilibili.com/"
    m = post["metrics"]
    assert all(m[k] is not None for k in ("likes", "comments", "shares", "collects", "views"))
    assert post["raw"]["aid"] and post["raw"]["cid"]


def test_get_comments():
    out = parsers.parse_get_comments(load("get_comments"))
    assert out["items"]
    c = out["items"][0]
    assert c["platform"] == "bilibili" and c["id"].isdigit()
    assert c["post_id"] and c["content"] and c["author"]["name"]
    assert c["publish_time"]
    roots = [i for i in out["items"] if i["parent_id"] is None]
    assert roots


def test_get_user():
    u = parsers.parse_get_user(load("get_user"))
    assert u["id"].isdigit() and u["name"]
    assert u["metrics"]["followers"] is not None and u["metrics"]["following"] is not None


def test_get_user_posts():
    out = parsers.parse_get_user_posts(load("get_user_posts"))
    assert out["items"] and out["total"]
    p = out["items"][0]
    assert p["id"].startswith("BV") and p["publish_time"]


def test_adapter_build_params_decodes_cursor():
    a = BilibiliAdapter()
    p = a.build_params("search_posts", {"keyword": "x", "cursor": encode_cursor({"page": 3})})
    assert p == {"keyword": "x", "page": 3}
    assert a.build_params("get_post", {"id": "BV1"}) == {"id": "BV1"}


def test_adapter_parse_dispatch():
    a = BilibiliAdapter()
    assert a.parse("echo", {"x": 1}) == {"x": 1}
    with pytest.raises(ValueError):
        a.parse("get_post", {"code": 0})
