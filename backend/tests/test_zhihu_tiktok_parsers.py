"""知乎 / TikTok parser tests on fixtures recorded through the user's Chrome (skip when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.tiktok import parsers as tp
from sociallens.platforms.zhihu import parsers as zp

FIX = Path(__file__).parent / "fixtures"


def load(platform: str, name: str):
    path = FIX / platform / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {platform}/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


# ---- 知乎 ---------------------------------------------------------------------------------


def test_zhihu_search_posts_two_pages():
    p1 = zp.parse_search_posts(load("zhihu", "search_posts"))
    p2 = zp.parse_search_posts(load("zhihu", "search_posts_page2"))
    assert len(p1["items"]) >= 10 and p1["cursor"] and p2["items"]
    a = p1["items"][0]
    assert a["id"].split(":")[0] in ("answer", "article", "question") and a["title"] and a["content"] and a["url"].startswith("https://")
    assert a["author"] and a["author"]["id"] and a["publish_time"]
    assert not ({i["id"] for i in p2["items"]} & {i["id"] for i in p1["items"]})


def test_zhihu_search_users_strips_highlight():
    out = zp.parse_search_users(load("zhihu", "search_users"))
    assert out["items"] and all("<em>" not in (u["name"] or "") for u in out["items"])
    assert out["items"][0]["url"].startswith("https://www.zhihu.com/people/") and out["items"][0]["metrics"]["followers"] is not None


def test_zhihu_post_user_from_ssr():
    p = zp.parse_get_post(load("zhihu", "get_post"))
    assert p["id"].startswith("answer:") and p["title"] and p["content"] and p["metrics"]["likes"] and p["metrics"]["comments"] and p["author"]["name"]
    u = zp.parse_get_user(load("zhihu", "get_user"))
    assert u["id"] and u["name"] and u["metrics"]["followers"] and u["metrics"]["posts"]


def test_zhihu_user_posts_feed_hot():
    up = zp.parse_get_user_posts(load("zhihu", "get_user_posts"))
    assert len(up["items"]) == 20 and up["cursor"] and up["items"][0]["id"].startswith("answer:")
    f = zp.parse_get_feed(load("zhihu", "get_feed"))
    assert f["items"] and all(i["id"].split(":")[0] in ("answer", "article", "question") for i in f["items"])
    t = zp.parse_get_trending(load("zhihu", "get_trending"))
    assert t["kind"] == "topics" and len(t["items"]) == 30 and t["items"][0]["title"] and t["items"][0]["heat"] and t["items"][0]["url"]


def test_zhihu_comments_and_replies():
    c = zp.parse_get_comments(load("zhihu", "get_comments"))
    assert c["items"] and c["items"][0]["content"] and c["items"][0]["author"]["name"]
    r = zp.parse_get_replies(load("zhihu", "get_replies"))
    assert r["items"] and r["items"][0]["parent_id"]
    o = zp.parse_get_replies(load("zhihu", "get_replies_overflow"))  # child_comment endpoint captured after expanding
    assert len(o["items"]) >= 10 and all(x["parent_id"] == "10447510852" for x in o["items"]) and o["cursor"]


# ---- TikTok ------------------------------------------------------------------------------


def test_tiktok_lists():
    s = tp.parse_search_posts(load("tiktok", "search_posts"))
    assert s["items"] and s["cursor"]
    v = s["items"][0]
    assert v["id"].isdigit() and v["author"]["id"] and v["url"] == f"https://www.tiktok.com/@{v['author']['id']}/video/{v['id']}"
    assert v["metrics"]["likes"] is not None and v["publish_time"] and v["media"] and v["media"][0]["extra"]["cookie_bound"]
    assert len(tp.parse_get_feed(load("tiktok", "get_feed"))["items"]) >= 5
    t = tp.parse_get_trending(load("tiktok", "get_trending"))
    assert t["kind"] == "posts" and t["items"]
    up = tp.parse_get_user_posts(load("tiktok", "get_user_posts"))
    assert len(up["items"]) >= 10 and up["cursor"]


def test_tiktok_search_users():
    out = tp.parse_search_users(load("tiktok", "search_users"))
    assert out["items"] and out["items"][0]["id"] and out["items"][0]["url"].startswith("https://www.tiktok.com/@")
    assert out["items"][0]["metrics"]["followers"] is not None


def test_tiktok_post_user_from_ssr():
    p = tp.parse_get_post(load("tiktok", "get_post"))
    assert p["id"].isdigit() and p["author"]["id"] and p["metrics"]["views"] and p["media"]
    u = tp.parse_get_user(load("tiktok", "get_user"))
    assert u["id"] and u["name"] and u["metrics"]["followers"] and u["metrics"]["posts"]


def test_tiktok_comments():
    c = tp.parse_get_comments(load("tiktok", "get_comments"))
    assert c["items"] and c["items"][0]["content"] and c["items"][0]["author"]["id"]


def test_tiktok_replies():
    r = tp.parse_get_replies(load("tiktok", "get_replies"))
    assert r["items"] and all(x["parent_id"] == r["items"][0]["parent_id"] for x in r["items"]) and r["items"][0]["content"]
