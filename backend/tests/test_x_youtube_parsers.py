"""Parser tests for X and YouTube fixtures recorded through the user's Chrome. Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.x import parsers as xp
from sociallens.platforms.youtube import parsers as yp

FIX = Path(__file__).parent / "fixtures"


def load(platform: str, name: str):
    path = FIX / platform / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {platform}/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


# ---- X ---------------------------------------------------------------------------


def test_x_search_posts():
    out = xp.parse_search_posts(load("x", "search_posts"))
    assert out["items"] and out["cursor"]
    t = out["items"][0]
    assert t["platform"] == "x" and t["id"].isdigit() and t["content"]
    assert t["author"]["id"] and t["author"]["name"] and t["url"].startswith("https://x.com/")
    assert t["publish_time"] and t["metrics"]["likes"] is not None


def test_x_search_users():
    out = xp.parse_search_users(load("x", "search_users"))
    assert out["items"]
    u = out["items"][0]
    assert u["id"] and u["name"] and u["metrics"]["followers"] and u["bio"]


def test_x_get_user():
    u = xp.parse_get_user(load("x", "get_user"))
    assert u["id"] and u["metrics"]["followers"] is not None and u["metrics"]["posts"]


def test_x_get_post_and_comments():
    p = xp.parse_get_post(load("x", "get_post"))
    assert p["id"] and p["content"]
    c = xp.parse_get_comments(load("x", "get_comments"))
    assert isinstance(c["items"], list)


def test_x_feed():
    out = xp.parse_get_feed(load("x", "get_feed"))
    assert len(out["items"]) > 10


def test_x_time():
    assert xp._time("Mon Sep 07 08:54:47 +0000 2026") == "2026-09-07T08:54:47+00:00"


# ---- YouTube ------------------------------------------------------------------------


def test_yt_search_posts():
    out = yp.parse_search_posts(load("youtube", "search_posts"))
    assert out["items"]
    v = out["items"][0]
    assert v["id"] and v["title"] and v["url"] == f"https://www.youtube.com/watch?v={v['id']}"
    assert v["cover_url"] and v["metrics"]["views"]


def test_yt_search_users():
    out = yp.parse_search_users(load("youtube", "search_users"))
    assert out["items"]
    c = out["items"][0]
    assert c["id"].startswith("UC") and c["name"]


def test_yt_get_post():
    p = yp.parse_get_post(load("youtube", "get_post"))
    assert p["id"] and p["title"] and p["author"]["name"] and p["metrics"]["views"] and p["publish_time"]
    assert p["metrics"]["likes"]


def test_yt_get_user():
    u = yp.parse_get_user(load("youtube", "get_user"))
    assert u["id"] and u["name"] and u["bio"]


def test_yt_user_posts_and_feed():
    up = yp.parse_get_user_posts(load("youtube", "get_user_posts"))
    assert up["items"]
    f = yp.parse_get_feed(load("youtube", "get_feed"))
    assert f["items"]


def test_yt_count():
    assert yp._count({"simpleText": "64,347,035次观看"}) == 64347035
    assert yp._count({"simpleText": "269万位订阅者"}) == 2690000
    assert yp._count("1.2M views") == 1200000


def test_yt_comments():
    out = yp.parse_get_comments(load("youtube", "get_comments"))
    assert len(out["items"]) >= 10 and out["cursor"]
    c = out["items"][0]
    assert c["id"] and c["author"]["name"] and c["content"] and c["likes"] is not None
    p2 = yp.parse_get_comments(load("youtube", "get_comments_page2"))
    assert len(p2["items"]) >= 10 and not ({i["id"] for i in p2["items"]} & {i["id"] for i in out["items"]})
