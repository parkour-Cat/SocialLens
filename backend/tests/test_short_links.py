"""Share short links: followed to the full link (only short-link hosts are ever requested), and
the comment digest by link. No network: httpx.MockTransport stands in for the sites."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from sociallens.api import resolve as resolve_mod
from sociallens.api.resolve import expand_short_link, resolve_link
from test_extension_link import _auth, _next_dispatch, _open

XHS_FULL = "https://www.xiaohongshu.com/discovery/item/64a1b2c3d4e5f60718293a4b?xsec_token=ABtok%3D&xsec_source=app_share"
REDIRECTS = {
    "b23.tv": ("https://www.bilibili.com/video/BV1rpWjevEip?share_source=copy", 302),
    "xhslink.com": (XHS_FULL, 307),
    "v.douyin.com": ("https://www.iesdouyin.com/share/video/7301234567890123456/?region=CN", 302),
    "t.co": ("https://b23.tv/abc", 301),  # short -> short -> full
}


def transport(seen: list[str], status_override: dict[str, int] | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.host)
        assert "cookie" not in req.headers
        loc, status = REDIRECTS.get(req.url.host, ("", 200))
        status = (status_override or {}).get(req.url.host, status)
        return httpx.Response(status, headers={"location": loc} if loc else {})

    return httpx.MockTransport(handler)


async def test_expands_common_share_links():
    seen: list[str] = []
    t = transport(seen)
    assert await expand_short_link("https://b23.tv/x7Kd2Lm", transport=t) == "https://www.bilibili.com/video/BV1rpWjevEip?share_source=copy"
    assert await expand_short_link("http://xhslink.com/a/AbCdEf", transport=t) == XHS_FULL
    assert await expand_short_link("https://t.co/zzz", transport=t) == "https://www.bilibili.com/video/BV1rpWjevEip?share_source=copy"
    # the destination sites themselves are never requested
    assert set(seen) <= {"b23.tv", "xhslink.com", "t.co"}


async def test_gives_up_on_non_redirects_and_loops():
    seen: list[str] = []
    assert await expand_short_link("https://b23.tv/x", transport=transport(seen, {"b23.tv": 200})) is None

    def loop(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://b23.tv/again"})

    assert await expand_short_link("https://b23.tv/x", transport=httpx.MockTransport(loop)) is None

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    assert await expand_short_link("https://b23.tv/x", transport=httpx.MockTransport(boom)) is None


async def test_resolve_link_returns_the_target_with_token():
    seen: list[str] = []
    r = await resolve_link("http://xhslink.com/a/AbCdEf", transport=transport(seen))
    assert r["platform"] == "xiaohongshu" and r["kind"] == "post" and r["id"] == "64a1b2c3d4e5f60718293a4b"
    assert r["xsec_token"] == "ABtok=" and r["short_link"] == "http://xhslink.com/a/AbCdEf"
    r = await resolve_link("https://v.douyin.com/iAbCdEf/", transport=transport(seen))
    assert (r["platform"], r["kind"], r["id"]) == ("douyin", "post", "7301234567890123456")
    # full links and bare ids never touch the network
    seen.clear()
    assert (await resolve_link("BV1rpWjevEip", transport=transport(seen)))["id"] == "BV1rpWjevEip"
    assert seen == []


def test_resolve_route_expands_and_can_be_told_not_to(client, monkeypatch):
    async def fake_expand(url, proxy=None, transport=None):
        return "https://www.bilibili.com/video/BV1rpWjevEip"

    monkeypatch.setattr(resolve_mod, "expand_short_link", fake_expand)
    r = client.get("/api/v1/resolve", params={"q": "https://b23.tv/abc"}).json()["data"]
    assert (r["platform"], r["kind"], r["id"], r["short_link"]) == ("bilibili", "post", "BV1rpWjevEip", "https://b23.tv/abc")
    r = client.get("/api/v1/resolve", params={"q": "https://b23.tv/abc", "expand": "false"}).json()["data"]
    assert r["kind"] == "short_link"


FIX = Path(__file__).parent / "fixtures" / "bilibili"


def _fixture(name: str):
    path = FIX / f"{name}.json"
    if not path.exists():
        pytest.skip(f"fixture bilibili/{name} not recorded yet")
    return json.loads(path.read_text(encoding="utf-8"))


def test_digest_by_link(client):
    post_raw, comments_raw = _fixture("get_post"), _fixture("get_comments")
    with _open(client) as ws:
        _auth(ws, actions={"bilibili": ["get_post", "get_comments"]})
        with ThreadPoolExecutor(1) as pool:
            fut = pool.submit(client.get, "/api/v1/comments/digest", params={"url": "https://www.bilibili.com/video/BV1rpWjevEip/?spm_id_from=333", "limit": 5})
            m = _next_dispatch(ws)
            assert m["action"] == "get_post" and m["params"]["id"] == "BV1rpWjevEip"
            ws.send_json({"type": "task.result", "id": m["id"], "ok": True, "payload": post_raw})
            m = _next_dispatch(ws)
            assert m["action"] == "get_comments" and m["params"]["post_id"] == "BV1rpWjevEip"
            ws.send_json({"type": "task.result", "id": m["id"], "ok": True, "payload": comments_raw})
            r = fut.result(timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["platform"] == "bilibili" and d["data"]["resolved"]["id"] == "BV1rpWjevEip" and d["data"]["top_comments"]


def test_digest_by_link_rejects_non_posts(client, monkeypatch):
    r = client.get("/api/v1/comments/digest", params={"url": "https://space.bilibili.com/12345"})
    assert r.status_code == 400 and "not a post link" in r.json()["error"]["message"]

    async def no_expand(url, proxy=None, transport=None):
        return None

    monkeypatch.setattr(resolve_mod, "expand_short_link", no_expand)
    r = client.get("/api/v1/comments/digest", params={"url": "https://b23.tv/abc"})
    assert r.status_code == 400 and "short link" in r.json()["error"]["message"]
