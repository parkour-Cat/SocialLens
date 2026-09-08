"""今日头条 parser tests on fixtures recorded through the user's Chrome (skip when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import decode_cursor
from sociallens.platforms.toutiao import ToutiaoAdapter
from sociallens.platforms.toutiao import parsers as tp

FIX = Path(__file__).parent / "fixtures" / "toutiao"


def load(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture toutiao/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def wrap(body, url="https://www.toutiao.com/x", tab=7):
    return {"url": url, "body": body, "_tab": tab}


def test_feed_and_paging():
    out = tp.parse_get_feed(wrap(load("get_feed")))
    assert len(out["items"]) >= 8 and out["cursor"] and decode_cursor(out["cursor"])["tab"] == 7
    p = out["items"][0]
    assert p["platform"] == "toutiao" and p["id"].isdigit() and p["title"] and p["url"].startswith("https://www.toutiao.com/")
    assert p["author"]["name"] and p["metrics"]["comments"] is not None and p["publish_time"]
    assert any(i["type"] == "video" for i in out["items"]) and any(i["type"] == "article" for i in out["items"])
    p2 = tp.parse_get_feed(wrap(load("get_feed_page2")))
    assert not ({i["id"] for i in p2["items"]} & {i["id"] for i in out["items"]})


def test_user_posts():
    out = tp.parse_get_user_posts(wrap(load("get_user_posts")))
    assert len(out["items"]) >= 5 and out["cursor"]
    assert all(i["id"].isdigit() and i["title"] for i in out["items"])
    assert any(i["metrics"]["likes"] is not None for i in out["items"])


def test_comments():
    raw = wrap(load("get_comments_page2"), url="https://www.toutiao.com/article/v4/tab_comments/?offset=20&count=20&group_id=7682605263174386218&item_id=7682605263174386218")
    out = tp.parse_get_comments(raw)
    assert len(out["items"]) >= 10 and out["total"] and out["cursor"]
    c = out["items"][0]
    assert c["post_id"] == "7682605263174386218" and c["id"].isdigit() and c["content"] and c["author"]["name"] and c["publish_time"]


def test_post_and_user_from_render_data():
    p = tp.parse_get_post(load("get_post"))
    assert p["id"] == "7682605263174386218" and p["title"] and p["content"] and p["author"]["name"] and p["metrics"]["likes"]
    assert p["media"] and p["media"][0]["type"] == "image" and p["publish_time"]
    u = tp.parse_get_user(load("get_user"))
    assert u["id"].startswith("MS4w") and u["name"] == "第一财经" and u["avatar_url"] and u["url"].endswith("/")


def test_search_cards():
    out = tp.parse_search_posts(wrap(load("search_posts_page2")))
    assert len(out["items"]) >= 5 and out["cursor"]
    p = out["items"][0]
    assert p["id"].isdigit() and p["title"] and p["url"].startswith("https://www.toutiao.com/")
    assert any(i["content"] for i in out["items"]) and any(i["raw"]["time_text"] for i in out["items"])


def test_replies_and_trending():
    r = tp.parse_get_replies({**wrap(load("get_replies")), "_comment_id": "1"})
    assert r["items"] and all(x["parent_id"] == "1" for x in r["items"]) and r["items"][0]["content"]
    t = tp.parse_get_trending(wrap(load("get_trending")))
    assert t["kind"] == "topics" and len(t["items"]) >= 20 and t["items"][0]["title"] and t["items"][0]["heat"]


def test_entry_urls():
    a = ToutiaoAdapter()
    b = a.build_params("get_post", {"id": "7682605263174386218"})
    assert b["url"] == "https://www.toutiao.com/article/7682605263174386218/" and b["page_params"]["post_id"] == "7682605263174386218"
    b = a.build_params("get_comments", {"post_id": "https://www.toutiao.com/video/123456789012/"})
    assert b["page_params"]["post_id"] == "123456789012" and b["keep_tab"]
    b = a.build_params("get_user", {"id": "MS4wLjABAAAAH3"})
    assert b["url"] == "https://www.toutiao.com/c/user/token/MS4wLjABAAAAH3/"
    b = a.build_params("search_posts", {"keyword": "无人机"})
    assert b["url"].startswith("https://so.toutiao.com/search?keyword=%E6%97%A0") and "pd=information" in b["url"]


def test_video_post_from_render_data():
    p = tp.parse_get_post(load("get_post_video"))
    assert p["id"] == "7683094941173547535" and p["type"] == "video" and p["title"] and p["author"]["name"] == "大河报"
    assert p["media"] and p["media"][0]["type"] == "video" and p["media"][0]["url"].startswith("https://") and p["media"][0]["width"] == 1280
    assert p["metrics"]["views"] is not None and p["publish_time"] and p["raw"]["duration"] == 172


def test_video_download_takes_best_quality_only():
    import asyncio

    p = tp.parse_get_post(load("get_post_video"))
    sources = asyncio.run(ToutiaoAdapter().download_sources(p, None, {}))
    assert len(sources) == 1 and sources[0]["type"] == "video" and sources[0]["url"] == p["media"][0]["url"]
