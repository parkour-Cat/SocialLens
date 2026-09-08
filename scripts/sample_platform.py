"""Record real payloads for a navigate-style platform as parser fixtures, using the user's Chrome.

Usage:
  uv run --project backend python scripts/sample_platform.py youtube [--keyword 露营]
  uv run --project backend python scripts/sample_platform.py x --keyword AI

Runs search_posts (2 pages), derives a post id and a user id from the search result with a
platform-specific finder, then get_post, get_comments (2 pages), get_user, get_user_posts
(2 pages), search_users and get_feed (2 pages). Saves to backend/tests/fixtures/<platform>/.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
BACKEND = os.environ.get("SOCIALLENS_URL", "http://127.0.0.1:17800")


def http(method: str, path: str, body: dict | None = None, timeout: float = 150) -> tuple[int, dict]:
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


def walk(obj: Any, pred: Callable[[dict], bool], depth: int = 0) -> dict | None:
    if depth > 40:
        return None
    if isinstance(obj, dict):
        if pred(obj):
            return obj
        for v in obj.values():
            r = walk(v, pred, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = walk(v, pred, depth + 1)
            if r is not None:
                return r
    return None


# platform -> (post id finder, user id finder) applied to the raw search_posts payload
FINDERS: dict[str, tuple[Callable[[Any], str | None], Callable[[Any], str | None]]] = {
    "youtube": (
        lambda raw: (walk(raw, lambda d: "videoId" in d and "title" in d and "ownerText" in d) or {}).get("videoId"),
        lambda raw: (
            (walk(raw, lambda d: "canonicalBaseUrl" in d and str(d.get("canonicalBaseUrl", "")).startswith("/@")) or {}).get("canonicalBaseUrl", "").lstrip("/")
            or (walk(raw, lambda d: "browseId" in d and str(d.get("browseId", "")).startswith("UC")) or {}).get("browseId")
        ),
    ),
    "x": (
        lambda raw: (walk(raw, lambda d: "rest_id" in d and "legacy" in d and "full_text" in (d.get("legacy") or {})) or {}).get("rest_id"),
        lambda raw: ((walk(raw, lambda d: "screen_name" in d) or {}).get("screen_name")),
    ),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("platform")
    ap.add_argument("--keyword", default="露营")
    ap.add_argument("--user-keyword", default=None)
    ap.add_argument("--anonymous", action="store_true", help="pass allow_anonymous (platform without a login requirement)")
    args = ap.parse_args()
    platform = args.platform
    fixtures = REPO / "backend" / "tests" / "fixtures" / platform
    find_post, find_user = FINDERS.get(platform, (lambda raw: None, lambda raw: None))

    def run(action: str, params: dict) -> dict | None:
        p = {**params, **({"allow_anonymous": True} if args.anonymous else {})}
        status, body = http("POST", f"/api/v1/{platform}/run", {"action": action, "params": p, "raw": True})
        if status != 200:
            print(f"  FAIL {action} {params}: {body.get('error')}")
            http("POST", f"/api/v1/{platform}/resume")
            return None
        return body["data"]

    def save(name: str, data) -> None:
        if isinstance(data, dict) and "url" in data and (data.get("status") != 200 or not isinstance(data.get("body"), dict)):
            print(f"  skip {name}: capture status {data.get('status')} with {type(data.get('body')).__name__} body")
            return
        fixtures.mkdir(parents=True, exist_ok=True)
        out = fixtures / f"{name}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ok   {name} -> {out.name} ({out.stat().st_size // 1024} KB)")

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

    st = http("GET", "/api/v1/status")[1]["data"]
    if not any("search_posts" in c.get("actions", {}).get(platform, []) for c in st["extension"]["connections"]):
        sys.exit(f"no connected extension build implements {platform} actions; reload it in chrome://extensions")
    if not st["platforms"].get(platform, {}).get("logged_in"):
        print(f"  warn Chrome is not logged in to {platform}")

    s1 = paged("search_posts", "search_posts", {"keyword": args.keyword})
    time.sleep(2)
    post_id = find_post(s1) if s1 else None
    user_id = find_user(s1) if s1 else None
    print(f"  using post {post_id}, user {user_id}")
    paged("search_users", "search_users", {"keyword": args.user_keyword or args.keyword}, pages=1)
    if post_id:
        d = run("get_post", {"id": post_id})
        if d:
            save("get_post", d)
        paged("get_comments", "get_comments", {"post_id": post_id})
    if user_id:
        u = run("get_user", {"id": user_id})
        if u:
            save("get_user", u)
        paged("get_user_posts", "get_user_posts", {"id": user_id})
    paged("get_feed", "get_feed", {})


if __name__ == "__main__":
    main()
