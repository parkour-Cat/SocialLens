"""get_replies / get_trending parsers against recorded fixtures (skip when a fixture is missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili import parsers as bp
from sociallens.platforms.douyin import parsers as dp
from sociallens.platforms.x import parsers as xp
from sociallens.platforms.xiaohongshu import parsers as hp
from sociallens.platforms.youtube import parsers as yp

FIX = Path(__file__).parent / "fixtures"


def load(platform: str, name: str):
    path = FIX / platform / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {platform}/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_replies(out: dict, platform: str):
    assert out["items"], "no replies parsed"
    parent = out["items"][0]["parent_id"]
    assert parent
    for c in out["items"]:
        assert c["platform"] == platform and c["id"] and c["id"] != parent and c["parent_id"] == parent
        assert c["content"] is not None and c["author"]["name"]


def _check_topics(out: dict, platform: str):
    assert out["kind"] == "topics" and out["items"]
    for t in out["items"]:
        assert t["type"] == "topic" and t["platform"] == platform and t["title"] and t["url"].startswith("https://") and t["rank"]


def test_bilibili_trending_and_replies():
    tr = bp.parse_get_trending(load("bilibili", "get_trending"))
    assert tr["kind"] == "posts" and len(tr["items"]) == 20 and tr["cursor"]
    v = tr["items"][0]
    assert v["id"].startswith("BV") and v["metrics"]["views"] and v["author"]["name"] and v["cover_url"]
    rp = bp.parse_get_replies(load("bilibili", "get_replies"))
    _check_replies(rp, "bilibili")
    assert rp["cursor"] and rp["total"]


def test_x_trending_and_replies():
    tr = xp.parse_get_trending(load("x", "get_trending"))
    _check_topics(tr, "x")
    rp = xp.parse_get_replies(load("x", "get_replies"))
    _check_replies(rp, "x")


def test_youtube_trending_and_replies():
    tr = yp.parse_get_trending(load("youtube", "get_trending"))
    assert tr["kind"] == "posts" and len(tr["items"]) >= 20 and tr["items"][0]["metrics"]["views"]
    rp = yp.parse_get_replies(load("youtube", "get_replies"))
    _check_replies(rp, "youtube")


def test_youtube_comments_expose_replies_token():
    out = yp.parse_get_comments(load("youtube", "get_comments"))
    assert any(c["raw"].get("replies_token") for c in out["items"])


def test_douyin_trending():
    tr = dp.parse_get_trending(load("douyin", "get_trending"))
    _check_topics(tr, "douyin")
    assert any(t["heat"] for t in tr["items"]) and any(t["category"] for t in tr["items"])


def test_douyin_replies():
    rp = dp.parse_get_replies(load("douyin", "get_replies"))
    _check_replies(rp, "douyin")
    assert rp["cursor"]  # first expand returns 3 replies, has_more for the rest


def test_xiaohongshu_trending_and_replies():
    tr = hp.parse_get_trending(load("xiaohongshu", "get_trending"))
    _check_topics(tr, "xiaohongshu")
    rp = hp.parse_get_replies(load("xiaohongshu", "get_replies"))
    _check_replies(rp, "xiaohongshu")


def test_x_heat():
    assert xp._heat("12.3K posts") == 12300 and xp._heat("1.2万 帖子") == 12000 and xp._heat("Trending in Sports") is None
