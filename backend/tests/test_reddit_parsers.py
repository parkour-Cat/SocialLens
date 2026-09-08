"""Reddit parser tests on fixtures recorded through the user's Chrome (skip when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.reddit import parsers as rp

FIX = Path(__file__).parent / "fixtures" / "reddit"


def load(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture reddit/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def test_search_posts_and_paging():
    out = rp.parse_search_posts(load("search_posts"))
    assert len(out["items"]) == 25 and out["cursor"]
    p = out["items"][0]
    assert p["platform"] == "reddit" and p["id"] and p["title"] and p["url"].startswith("https://www.reddit.com/r/")
    assert p["author"]["name"] and p["metrics"]["likes"] and p["metrics"]["comments"] and p["publish_time"]
    assert all(i["type"] in ("video", "image", "article", "text") for i in out["items"])
    p2 = rp.parse_search_posts(load("search_posts_page2"))
    assert not ({i["id"] for i in p2["items"]} & {i["id"] for i in out["items"]})


def test_video_media_has_audio_track():
    posts = rp.parse_search_posts(load("search_posts"))["items"] + rp.parse_get_trending(load("get_trending"))["items"]
    v = next(i for i in posts if i["type"] == "video")
    m = v["media"][0]
    assert m["url"].startswith("https://v.redd.it/") and m["extra"]["audio_url"].endswith("DASH_AUDIO_128.mp4")


def test_search_users():
    out = rp.parse_search_users(load("search_users"))
    assert out["items"] and out["items"][0]["id"] and out["items"][0]["url"].startswith("https://www.reddit.com/user/")
    assert out["items"][0]["raw"]["total_karma"]


def test_post_comments_replies():
    p = rp.parse_get_post(load("get_post"))
    assert p["id"] and p["title"] and p["metrics"]["comments"]
    c = rp.parse_get_comments(load("get_comments"))
    assert len(c["items"]) > 50 and c["total"] and c["items"][0]["content"] and c["items"][0]["post_id"] == p["id"]
    r = rp.parse_get_replies(load("get_replies"))
    assert r["items"] and all(x["parent_id"] == r["items"][0]["parent_id"] for x in r["items"])


def test_user_and_posts_and_feed():
    u = rp.parse_get_user(load("get_user"))
    assert u["id"] and u["name"] and u["raw"]["total_karma"]
    up = rp.parse_get_user_posts(load("get_user_posts"))
    assert up["items"] and up["items"][0]["author"]["id"] == u["id"]
    assert len(rp.parse_get_feed(load("get_feed"))["items"]) == 25
    t = rp.parse_get_trending(load("get_trending"))
    assert t["kind"] == "posts" and len(t["items"]) == 25


def test_comments_page_through_morechildren():
    first = rp.parse_get_comments(load("get_comments"))
    assert first["cursor"]  # the listing's "more" stub names the rest of the top-level comments
    more = rp.parse_get_comments({**load("get_comments_more"), "_rest": ["abc"]})
    assert more["items"] and more["cursor"]
    assert all(c["content"] for c in more["items"]) and any(not c["parent_id"] for c in more["items"])
    assert not ({c["id"] for c in more["items"]} & {c["id"] for c in first["items"]})
