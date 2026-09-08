"""Record real 小红书 payloads as parser fixtures, using the user's logged-in Chrome.

Each action opens a temporary background tab (navigate strategy) in the connected browser and
returns the raw page payload; pagination is sampled by scrolling the same tab. Saves to
backend/tests/fixtures/xiaohongshu/. Needs: backend running, extension reloaded with the
xiaohongshu actions, Chrome logged in to 小红书.

Usage: uv run --project backend python scripts/sample_xiaohongshu.py
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

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "backend" / "tests" / "fixtures" / "xiaohongshu"
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
    status, body = http("POST", "/api/v1/xiaohongshu/run", {"action": action, "params": params, "raw": True})
    if status != 200:
        print(f"  FAIL {action} {params}: {body.get('error')}")
        http("POST", "/api/v1/xiaohongshu/resume")
        return None
    return body["data"]


def save(name: str, data) -> None:
    # Never overwrite a good fixture with a failed capture (status 0 / non-JSON body).
    if isinstance(data, dict) and "url" in data and (data.get("status") != 200 or not isinstance(data.get("body"), dict)):
        print(f"  skip {name}: capture status {data.get('status')} with {type(data.get('body')).__name__} body, keeping the existing fixture")
        return
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / f"{name}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ok   {name} -> {out.name} ({out.stat().st_size // 1024} KB)")


def main() -> None:
    st = http("GET", "/api/v1/status")[1]["data"]
    conns = [c for c in st["extension"]["connections"] if "search_posts" in c.get("actions", {}).get("xiaohongshu", [])]
    if not conns:
        sys.exit("no connected extension build implements xiaohongshu actions; reload it in chrome://extensions")
    if not st["platforms"].get("xiaohongshu", {}).get("logged_in"):
        sys.exit("Chrome is not logged in to 小红书")
    failures = 0

    # search page 1 + page 2 (scroll in the kept tab)
    s1 = run("search_posts", {"keyword": KEYWORD})
    tab = s1.get("_tab") if s1 else None
    if s1:
        save("search_posts", s1)
        s2 = run("search_posts", {"keyword": KEYWORD, "cursor": cursor({"tab": tab})}) if tab else None
        if s2:
            save("search_posts_page2", s2)
        else:
            failures += 1
    else:
        failures += 1
    time.sleep(2)

    # pick a note + user from search results for the detail actions
    note_id = token = user_id = user_token = None
    try:
        source = s1 or json.loads((FIXTURES / "search_posts.json").read_text(encoding="utf-8"))
        items = source["body"]["data"]["items"] if "body" in source else source["data"]["items"]
        first = next(i for i in items if i.get("model_type") == "note")
        note_id, token = first["id"], first.get("xsec_token")
        user = first["note_card"]["user"]
        user_id, user_token = user["user_id"], user.get("xsec_token")
        print(f"  using note {note_id}, user {user_id}")
    except Exception as e:  # noqa: BLE001
        print(f"  warn cannot derive ids from search result: {e!r}")

    # search_users: the site ignores ?type=user and only fetches usersearch when the tab is
    # clicked in the UI; deferred (see docs/platforms/xiaohongshu.md).

    if note_id:
        d = run("get_post", {"id": note_id, "xsec_token": token})
        if d:
            save("get_post", d)
        else:
            failures += 1
        c1 = run("get_comments", {"post_id": note_id, "xsec_token": token})
        if c1:
            save("get_comments", c1)
            ctab = c1.get("_tab")
            c2 = run("get_comments", {"post_id": note_id, "cursor": cursor({"tab": ctab})}) if ctab else None
            if c2:
                save("get_comments_page2", c2)
            else:
                failures += 1
        else:
            failures += 1

    if user_id:
        p = run("get_user", {"id": user_id, "xsec_token": user_token})
        if p:
            save("get_user", p)
        else:
            failures += 1
        n1 = run("get_user_posts", {"id": user_id, "xsec_token": user_token})
        if n1:
            save("get_user_posts", n1)
            ntab = n1.get("_tab")
            n2 = run("get_user_posts", {"id": user_id, "cursor": cursor({"tab": ntab})}) if ntab else None
            if n2:
                save("get_user_posts_page2", n2)
            else:
                failures += 1
        else:
            failures += 1

    f1 = run("get_feed", {})
    if f1:
        save("get_feed", f1)
        ftab = f1.get("_tab")
        f2 = run("get_feed", {"cursor": cursor({"tab": ftab})}) if ftab else None
        if f2:
            save("get_feed_page2", f2)
        else:
            failures += 1
    else:
        failures += 1

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
