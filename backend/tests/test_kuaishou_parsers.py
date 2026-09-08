"""Parser tests for 快手 payloads recorded through the user's Chrome. Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import encode_cursor
from sociallens.platforms.kuaishou import KuaishouAdapter, parsers

FIXTURES = Path(__file__).parent / "fixtures" / "kuaishou"


def load(name: str):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name} not recorded yet (run scripts/sample_kuaishou.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_post(p: dict) -> None:
    assert p["platform"] == "kuaishou" and p["id"] and p["type"] == "video"
    assert p["url"] == f"https://www.kuaishou.com/short-video/{p['id']}"
    assert p["author"]["id"] and p["author"]["name"]
    assert p["metrics"]["likes"] is not None and p["publish_time"]
    assert p["cover_url"] and any(m["type"] == "video" and m["url"].startswith("http") for m in p["media"])


def test_search_posts():
    out = parsers.parse_search_posts(load("search_posts"))
    assert out["items"]
    _check_post(out["items"][0])


def test_search_users():
    out = parsers.parse_search_users(load("search_users"))
    assert out["items"]
    u = out["items"][0]
    assert u["id"] and u["name"] and u["url"].startswith("https://www.kuaishou.com/profile/")


def test_get_feed():
    out = parsers.parse_get_feed(load("get_feed"))
    assert len(out["items"]) >= 10
    _check_post(out["items"][0])
    assert out["items"][0]["metrics"]["likes"] > 1000  # '46.4万' style strings are converted


def test_get_user_posts():
    out = parsers.parse_get_user_posts(load("get_user_posts"))
    assert out["items"]
    _check_post(out["items"][0])


def test_get_post():
    post = parsers.parse_get_post(load("get_post"))
    _check_post(post)
    assert post["tags"]


def test_get_user():
    u = parsers.parse_get_user(load("get_user"))
    assert u["id"] and u["name"] and u["metrics"]["followers"] and u["metrics"]["posts"]
    assert u["raw"]["kwai_id"]


def test_get_comments():
    out = parsers.parse_get_comments(load("get_comments"))
    assert isinstance(out["items"], list)
    if out["items"]:
        c = out["items"][0]
        assert c["post_id"] and c["content"] and c["author"]["name"]


def test_count_conversion():
    assert parsers._count("46.4万") == 464000
    assert parsers._count("1.2亿") == 120000000
    assert parsers._count(15) == 15 and parsers._count("") is None


def test_build_params():
    a = KuaishouAdapter()
    p = a.build_params("search_posts", {"keyword": "露营"})
    assert p["_strategy"] == "navigate" and "/search/video?searchKey=" in p["url"] and p["keep_tab"]
    p = a.build_params("get_post", {"id": "3x"})
    assert p["url"] == "https://www.kuaishou.com/short-video/3x" and not p["keep_tab"]
    assert a.build_params("get_feed", {"cursor": encode_cursor({"tab": 9})}) == {"_strategy": "call", "_tab": 9, "more": True}
