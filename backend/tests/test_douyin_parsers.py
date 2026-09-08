"""Parser tests against recorded 抖音 payloads (scripts/sample_douyin.py). Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import encode_cursor
from sociallens.platforms.douyin import DouyinAdapter, parsers

FIXTURES = Path(__file__).parent / "fixtures" / "douyin"


def load(name: str):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name} not recorded yet (run scripts/sample_douyin.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def _first_existing(*names: str):
    for n in names:
        if (FIXTURES / f"{n}.json").exists():
            return load(n)
    pytest.skip(f"none of {names} recorded")


def test_search_posts():
    out = parsers.parse_search_posts(_first_existing("search_posts", "search_posts_page2"))
    assert out["items"]
    p = out["items"][0]
    assert p["platform"] == "douyin" and p["id"].isdigit()
    assert p["url"] == f"https://www.douyin.com/video/{p['id']}"
    assert p["author"]["id"].startswith("MS4wLjAB") and p["author"]["name"]
    assert p["metrics"]["likes"] is not None and p["metrics"]["comments"] is not None
    assert p["publish_time"] and p["cover_url"]
    vids = [m for m in p["media"] if m["type"] == "video"]
    assert vids and vids[0]["url"].startswith("https://") and vids[0]["headers"]["Referer"]
    assert len({i["id"] for i in out["items"]}) == len(out["items"])


def test_search_users():
    out = parsers.parse_search_users(load("search_users"))
    assert out["items"]
    u = out["items"][0]
    assert u["id"].startswith("MS4wLjAB") and u["name"] and u["avatar_url"]
    assert u["metrics"]["followers"] is not None
    assert u["bio"] is not None


def test_get_post():
    post = parsers.parse_get_post(load("get_post"))
    assert post["id"] and post["author"]["id"] and post["media"]


def test_get_comments():
    out = parsers.parse_get_comments(load("get_comments"))
    assert out["items"]
    c = out["items"][0]
    assert c["post_id"] and c["content"] and c["author"]["name"] and c["publish_time"]


def test_get_user():
    u = parsers.parse_get_user(load("get_user"))
    assert u["id"] and u["name"] and u["metrics"]["followers"] is not None


def test_get_user_posts():
    out = parsers.parse_get_user_posts(load("get_user_posts"))
    assert out["items"] and out["items"][0]["id"]


def test_get_feed():
    out = parsers.parse_get_feed(load("get_feed"))
    assert out["items"] and out["items"][0]["author"]["name"]


def test_build_params():
    a = DouyinAdapter()
    p = a.build_params("search_posts", {"keyword": "露营"})
    assert p["_strategy"] == "navigate" and p["url"].startswith("https://www.douyin.com/search/") and p["url"].endswith("?type=video")
    p = a.build_params("get_post", {"id": "123"})
    assert p["url"] == "https://www.douyin.com/video/123" and not p["keep_tab"]
    p = a.build_params("get_user_posts", {"id": "MS4w", "cursor": encode_cursor({"tab": 7})})
    assert p == {"_strategy": "call", "_tab": 7, "more": True}
