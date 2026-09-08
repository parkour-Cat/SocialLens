"""Instagram parser tests on fixtures recorded through the user's Chrome (skip when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.instagram import InstagramAdapter
from sociallens.platforms.instagram import parsers as ip

FIX = Path(__file__).parent / "fixtures" / "instagram"


def load(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture instagram/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def wrap(body, tab=9):
    return {"url": "https://www.instagram.com/graphql/query", "body": body, "_tab": tab}


def test_feed():
    out = ip.parse_get_feed(wrap(load("get_feed")))
    assert len(out["items"]) >= 3 and out["cursor"]  # a timeline page mixes posts with suggestion units
    p = out["items"][0]
    assert p["platform"] == "instagram" and p["id"].isdigit() and p["url"].startswith("https://www.instagram.com/")
    assert p["author"]["name"] and p["author"]["url"] and p["publish_time"] and p["cover_url"]
    assert all(i["type"] in ("video", "image") for i in out["items"])


def test_user_and_posts():
    u = ip.parse_get_user(wrap(load("get_user")))
    assert u["id"].isdigit() and u["name"] and u["metrics"]["followers"] and u["metrics"]["posts"] and u["raw"]["full_name"]
    out = ip.parse_get_user_posts(wrap(load("get_user_posts")))
    assert len(out["items"]) >= 10 and out["cursor"]
    assert all(i["author"]["name"] for i in out["items"]) and any(i["metrics"]["likes"] for i in out["items"])
    assert any(i["media"] for i in out["items"])


def test_search_posts():
    out = ip.parse_search_posts(wrap(load("search_posts")))
    assert len(out["items"]) >= 15 and out["cursor"]
    assert all(i["url"] and i["author"]["name"] for i in out["items"]) and any(i["content"] for i in out["items"])


def test_post_and_comments_from_page():
    p = ip.parse_get_post(load("get_post"))
    assert p["id"].isdigit() and p["raw"]["code"] == "Dbru79IAdH-" and p["author"]["name"] == "natgeo" and p["metrics"]["comments"] and p["media"]
    c = ip.parse_get_comments({**load("get_comments"), "_tab": 9})
    assert len(c["items"]) >= 10 and c["cursor"]
    x = c["items"][0]
    assert x["post_id"] == "Dbru79IAdH-" and x["content"] and x["author"]["name"] and x["publish_time"] and x["raw"]["reply_count"] is not None
    c2 = ip.parse_get_comments({**wrap(load("get_comments_page2")), "_post_id": "Dbru79IAdH-"})
    assert len(c2["items"]) >= 10 and c2["cursor"] and not ({i["id"] for i in c2["items"]} & {i["id"] for i in c["items"]})


def test_search_users_replies_trending():
    u = ip.parse_search_users(wrap(load("search_users")))
    assert u["items"] and u["items"][0]["name"] and u["items"][0]["avatar_url"]
    r = ip.parse_get_replies({**wrap(load("get_replies")), "_comment_id": "1", "_post_id": "X"})
    assert r["items"] and all(x["parent_id"] == "1" and x["post_id"] == "X" for x in r["items"])
    t = ip.parse_get_trending({**load("get_trending"), "_tab": 9})
    assert len(t["items"]) >= 10 and t["items"][0]["url"] and t["cursor"]
    t2 = ip.parse_get_trending(wrap(load("get_trending_page2")))
    assert len(t2["items"]) >= 10 and t2["cursor"]


def test_entry_urls():
    a = InstagramAdapter()
    b = a.build_params("get_post", {"id": "https://www.instagram.com/reel/AbC123/"})
    assert b["url"] == "https://www.instagram.com/reel/AbC123/" and b["page_params"]["post_id"] == "AbC123"
    b = a.build_params("get_comments", {"post_id": "AbC123"})
    assert b["url"] == "https://www.instagram.com/p/AbC123/" and b["keep_tab"]
    b = a.build_params("get_user", {"id": "@natgeo"})
    assert b["url"] == "https://www.instagram.com/natgeo/" and b["page_params"]["id"] == "natgeo"
    b = a.build_params("search_posts", {"keyword": "cat"})
    assert b["url"] == "https://www.instagram.com/explore/search/keyword/?q=cat"
