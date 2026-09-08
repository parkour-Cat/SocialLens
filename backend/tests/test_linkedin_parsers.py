"""LinkedIn parser tests on voyager fixtures recorded through the user's Chrome (skip when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import decode_cursor
from sociallens.platforms.linkedin import LinkedinAdapter
from sociallens.platforms.linkedin import parsers as lp

FIX = Path(__file__).parent / "fixtures" / "linkedin"


def load(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture linkedin/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def wrap(body, url="https://www.linkedin.com/voyager/api/x"):
    return {"url": url, "body": body}


def test_feed():
    out = lp.parse_get_feed(wrap(load("get_feed")))
    assert len(out["items"]) >= 5 and out["total"] == 7
    p = out["items"][0]
    assert p["platform"] == "linkedin" and p["id"].isdigit() and p["url"].startswith("https://www.linkedin.com/feed/update/urn:li:activity:")
    assert p["author"]["name"] and p["content"] and p["metrics"]["likes"] is not None
    assert out["cursor"] is None  # 7 posts in total, all in the first page


def test_post_with_comments():
    p = lp.parse_get_post(wrap(load("get_post")))
    assert p["id"].isdigit() and p["content"] and p["author"]["name"] and p["metrics"]["likes"] is not None
    assert p["raw"]["comments"] and p["raw"]["comments"][0]["content"] and p["raw"]["comments"][0]["author"]["name"]


def test_user():
    u = lp.parse_get_user(wrap(load("get_user"), url="https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity=williamhgates&decorationId=x"))
    assert u["id"] == "williamhgates" and u["name"] == "Bill Gates" and u["bio"] and u["avatar_url"].startswith("https://media.licdn.com/")
    assert u["raw"]["urn"].startswith("urn:li:fsd_profile:") and u["raw"]["location"]


def test_search_users_and_typeahead():
    out = lp.parse_search_users(wrap(load("search_users"), url="https://www.linkedin.com/voyager/api/graphql?variables=(start:0,...)&queryId=x"))
    # out-of-network members come back as anonymous "领英会员" rows without a profile url and are dropped
    assert len(out["items"]) >= 1 and out["total"] and out["cursor"] and decode_cursor(out["cursor"])["start"] == 10
    assert all(i["url"].startswith("https://www.linkedin.com/in/") and i["name"] for i in out["items"])
    t = lp.parse_search_users(wrap(load("search_users_typeahead")))  # suggestions are mostly queries / companies
    assert t["cursor"] is None and all(i["url"].startswith("https://www.linkedin.com/in/") for i in t["items"])


def test_build_params():
    a = LinkedinAdapter()
    assert a.build_params("get_post", {"id": "https://www.linkedin.com/feed/update/urn:li:activity:7493150338116382720/"})["id"] == "7493150338116382720"
    assert a.build_params("get_post", {"id": "urn:li:activity:7493150338116382720"})["id"] == "7493150338116382720"
    assert a.build_params("get_user", {"id": "https://www.linkedin.com/in/williamhgates/"})["id"] == "williamhgates"
    b = a.build_params("get_user_posts", {"id": "jenhsunhuang"})
    assert b["url"] == "https://www.linkedin.com/in/jenhsunhuang/recent-activity/all/" and b["_strategy"] == "navigate" and b["keep_tab"]
    b = a.build_params("get_comments", {"post_id": "urn:li:activity:7492928527202394113"})
    assert b["url"] == "https://www.linkedin.com/feed/update/urn:li:activity:7492928527202394113/" and b["page_params"]["post_id"] == "7492928527202394113"
    b = a.build_params("get_feed", {"cursor": __import__("sociallens.platforms.bilibili.cursor", fromlist=["encode_cursor"]).encode_cursor({"start": 10, "token": "t"})})
    assert b["start"] == 10 and b["token"] == "t"


def test_user_posts_from_classic_page():
    out = lp.parse_get_user_posts(load("get_user_posts"))
    assert len(out["items"]) >= 15 and out["cursor"]
    p = out["items"][0]
    assert p["id"].isdigit() and p["content"] and p["author"]["name"] == "Jensen Huang" and p["metrics"]["likes"]
    assert any(i["media"] for i in out["items"]) and all(i["url"].startswith("https://www.linkedin.com/feed/update/") for i in out["items"])


def test_comments_and_replies_from_classic_page():
    c = lp.parse_get_comments({**load("get_post_page"), "_tab": 5, "_post_id": "7492928527202394113"})
    assert len(c["items"]) >= 8 and c["total"] == 114 and c["cursor"]  # the page renders the first 8 top-level comments
    x = c["items"][0]
    assert x["post_id"] == "7492928527202394113" and x["content"] and x["author"]["name"] and x["publish_time"] and x["raw"]["reply_count"] is not None
    c2 = lp.parse_get_comments({**load("get_comments_page2"), "_post_id": "7492928527202394113"})
    assert len(c2["items"]) >= 8 and c2["cursor"] and not ({i["id"] for i in c2["items"]} & {i["id"] for i in c["items"]})
    r = lp.parse_get_replies({**load("get_replies"), "_post_id": "7492928527202394113", "_comment_id": "7492930584621776896"})
    assert r["items"] and all(i["parent_id"] == "7492930584621776896" for i in r["items"]) and r["items"][0]["content"]
