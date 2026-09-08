"""Record real 快手 payloads as parser fixtures, using the user's logged-in Chrome.

Usage: uv run --project backend python scripts/sample_kuaishou.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "backend" / "tests" / "fixtures" / "kuaishou"
BACKEND = os.environ.get("SOCIALLENS_URL", "http://127.0.0.1:17800")
KEYWORD = os.environ.get("KEYWORD", "露营")


def http(method: str, path: str, body: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    req = urllib.request.Request(BACKEND + path, method=method)
    data = None
    if body is not None:
        req.add_header("content-type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def cursor(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")


def run(action: str, params: dict) -> dict | None:
    status, body = http("POST", "/api/v1/kuaishou/run", {"action": action, "params": {**params, "allow_anonymous": True}, "raw": True})
    if status != 200:
        print(f"  FAIL {action} {params}: {body.get('error')}")
        http("POST", "/api/v1/kuaishou/resume")
        return None
    return body["data"]


def save(name: str, data) -> None:
    if isinstance(data, dict) and "url" in data and (data.get("status") != 200 or not isinstance(data.get("body"), dict)):
        print(f"  skip {name}: capture status {data.get('status')} with {type(data.get('body')).__name__} body")
        return
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / f"{name}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ok   {name} -> {out.name} ({out.stat().st_size // 1024} KB)")


def find_first(obj: Any, pred) -> Any:
    if isinstance(obj, dict):
        if pred(obj):
            return obj
        for v in obj.values():
            r = find_first(v, pred)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_first(v, pred)
            if r is not None:
                return r
    return None


def paged(name: str, action: str, params: dict, pages: int = 2) -> dict | None:
    first = run(action, params)
    if not first:
        return None
    save(name, first)
    tab = first.get("_tab")
    for n in range(2, pages + 1):
        if not tab:
            break
        nxt = run(action, {**params, "cursor": cursor({"tab": tab})})
        if not nxt or nxt.get("end"):
            print(f"  info {name}: no page {n}")
            break
        save(f"{name}_page{n}", nxt)
    return first


def main() -> None:
    st = http("GET", "/api/v1/status")[1]["data"]
    if not any("search_posts" in c.get("actions", {}).get("kuaishou", []) for c in st["extension"]["connections"]):
        sys.exit("no connected extension build implements kuaishou actions; reload it in chrome://extensions")
    if not st["platforms"].get("kuaishou", {}).get("logged_in"):
        print("  warn Chrome is not logged in to 快手; search may show a login wall")
    s1 = paged("search_posts", "search_posts", {"keyword": KEYWORD})
    time.sleep(2)
    photo = find_first(s1, lambda d: "photo" in d and isinstance(d.get("photo"), dict) and "id" in d["photo"]) if s1 else None
    photo_id = (photo or {}).get("photo", {}).get("id")
    author = (photo or {}).get("author") or {}
    user_id = author.get("id")
    print(f"  using photo {photo_id}, user {user_id}")
    paged("search_users", "search_users", {"keyword": "人民日报"}, pages=1)
    if photo_id:
        d = run("get_post", {"id": photo_id})
        if d:
            save("get_post", d)
        paged("get_comments", "get_comments", {"post_id": photo_id})
    if user_id:
        u = run("get_user", {"id": user_id})
        if u:
            save("get_user", u)
        paged("get_user_posts", "get_user_posts", {"id": user_id})
    paged("get_feed", "get_feed", {})


if __name__ == "__main__":
    main()
