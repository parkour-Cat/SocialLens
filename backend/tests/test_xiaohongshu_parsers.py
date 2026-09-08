"""Parser tests against recorded 小红书 payloads (scripts/sample_xiaohongshu.py). Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import decode_cursor, encode_cursor
from sociallens.platforms.xiaohongshu import XiaohongshuAdapter, parsers

FIXTURES = Path(__file__).parent / "fixtures" / "xiaohongshu"


def load(name: str):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name} not recorded yet (run scripts/sample_xiaohongshu.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def test_search_posts():
    out = parsers.parse_search_posts(load("search_posts"))
    assert out["items"]
    p = out["items"][0]
    assert p["platform"] == "xiaohongshu" and p["type"] in ("image", "video")
    assert p["title"] and p["author"]["id"] and p["author"]["name"]
    assert p["url"].startswith("https://www.xiaohongshu.com/explore/")
    assert "xsec_token=" in p["url"]
    assert p["cover_url"].startswith("http")
    assert p["metrics"]["likes"] is not None and p["metrics"]["comments"] is not None
    assert p["raw"]["xsec_token"]


def test_get_feed_ssr():
    out = parsers.parse_get_feed(load("get_feed"))
    assert out["items"]
    p = out["items"][0]
    assert p["id"] and p["author"]["name"] and p["cover_url"]
    assert p["metrics"]["likes"] is not None


def test_get_post():
    post = parsers.parse_get_post(load("get_post"))
    assert post["id"] and post["title"] is not None and post["author"]["id"]
    assert post["media"] and post["publish_time"]


def test_get_comments():
    out = parsers.parse_get_comments(load("get_comments"))
    assert out["items"]
    c = out["items"][0]
    assert c["post_id"] and c["content"] and c["author"]["name"] and c["publish_time"]


def test_get_user():
    u = parsers.parse_get_user(load("get_user"))
    assert u["id"] and u["name"]
    assert u["metrics"]["followers"] is not None


def test_get_user_posts():
    out = parsers.parse_get_user_posts(load("get_user_posts"))
    assert out["items"] and out["items"][0]["id"]


def test_build_params_first_page_navigates():
    a = XiaohongshuAdapter()
    p = a.build_params("search_posts", {"keyword": "露营"})
    assert p["_strategy"] == "navigate" and "search_result?keyword=" in p["url"] and p["page_action"] == "search_posts" and p["keep_tab"]
    p = a.build_params("get_post", {"id": "abc", "xsec_token": "T"})
    assert p["url"] == "https://www.xiaohongshu.com/explore/abc?xsec_token=T&xsec_source=pc_search" and not p["keep_tab"]


def test_build_params_cursor_continues_in_tab():
    a = XiaohongshuAdapter()
    p = a.build_params("search_posts", {"keyword": "x", "cursor": encode_cursor({"tab": 42})})
    assert p == {"_strategy": "call", "_tab": 42, "more": True}
    assert decode_cursor(encode_cursor({"tab": 42})) == {"tab": 42}


def test_generic_actions_pass_through():
    a = XiaohongshuAdapter()
    assert a.build_params("read_global", {"path": "x", "_tab": 1}) == {"path": "x", "_tab": 1}


def test_second_pages_from_api_captures():
    c2 = parsers.parse_get_comments(load("get_comments_page2"))
    assert c2["items"] and c2["items"][0]["post_id"]
    f2 = parsers.parse_get_feed(load("get_feed_page2"))
    assert f2["items"] and f2["items"][0]["metrics"]["likes"] is not None
    n2 = parsers.parse_get_user_posts(load("get_user_posts_page2"))
    assert n2["items"] and n2["items"][0]["publish_time"]
    s2 = parsers.parse_search_posts(load("search_posts_page2"))
    assert s2["items"]


def test_search_users():
    out = parsers.parse_search_users(load("search_users"))
    assert len(out["items"]) == 15 and out["cursor"]
    u = out["items"][0]
    assert u["id"] and u["name"] and u["avatar_url"] and u["metrics"]["followers"] and u["metrics"]["posts"]
    assert "xsec_token=" in u["url"] and u["raw"]["xsec_token"]
    p2 = parsers.parse_search_users(load("search_users_page2"))
    assert p2["items"] and not ({x["id"] for x in p2["items"]} & {x["id"] for x in out["items"]})