"""Parser tests for 公众号 payloads recorded through the user's backend session. Missing fixtures skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sociallens.platforms.bilibili.cursor import decode_cursor, encode_cursor
from sociallens.platforms.weixin_mp import WeixinMpAdapter, parsers

FIXTURES = Path(__file__).parent / "fixtures" / "weixin_mp"


def load(name: str):
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture {name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def test_search_users():
    out = parsers.parse_search_users(load("search_users"))
    assert out["items"]
    u = out["items"][0]
    assert u["platform"] == "weixin_mp" and u["id"].endswith("=") and u["name"] == "人民日报"
    assert u["avatar_url"].startswith("http") and u["bio"]
    assert u["raw"]["alias"] == "rmrbwx"
    # searchbiz reports `total`; a next cursor exists only when more than one page matched
    if out["total"] is not None and int(out["total"]) > 5:
        assert decode_cursor(out["cursor"]) == {"begin": 5}
    else:
        assert out["cursor"] is None


def test_get_user_posts():
    out = parsers.parse_get_user_posts(load("get_user_posts"))
    assert out["items"]
    a = out["items"][0]
    assert a["type"] == "article" and a["title"] and a["url"].startswith("http")
    assert a["publish_time"]


def test_freq_control_is_an_error():
    with pytest.raises(ValueError, match="200013"):
        parsers.parse_get_user_posts({"base_resp": {"ret": 200013, "err_msg": "freq control"}})


def test_get_post():
    post = parsers.parse_get_post(load("get_post"))
    assert post["type"] == "article" and post["title"] and post["content"] and post["url"]


def test_build_params():
    a = WeixinMpAdapter()
    assert a.build_params("search_users", {"keyword": "x"}) == {"keyword": "x", "begin": 0}
    assert a.build_params("get_user_posts", {"id": "F", "cursor": encode_cursor({"begin": 10})}) == {"id": "F", "begin": 10}
    p = a.build_params("get_post", {"id": "AbCd"})
    assert p["_strategy"] == "navigate" and p["url"] == "https://mp.weixin.qq.com/s/AbCd" and p["page_action"] == "get_post"
    p = a.build_params("get_post", {"id": "https://mp.weixin.qq.com/s?__biz=x&mid=1"})
    assert p["url"].startswith("https://mp.weixin.qq.com/s?__biz=")
