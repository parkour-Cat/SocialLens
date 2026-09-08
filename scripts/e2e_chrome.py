"""End-to-end check with a real headless Chromium driven by Playwright.

Loads the built extension into a throwaway profile (its ID is fixed by the manifest `key`,
so the backend accepts it by Origin without any token), then drives the running backend's
REST API through the full chain:
REST -> backend -> WebSocket -> service worker -> page script -> site -> back.

Prerequisites:
  backend running on 127.0.0.1:17800        (uv run sociallens, in backend/)
  extension built                            (pnpm build, in extension/)
  playwright chromium installed once         (uv run python -m playwright install chromium, in backend/)
Usage:
  uv run --project backend python scripts/e2e_chrome.py
Set HEADED=1 to watch it in a visible window.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
EXT_DIST = REPO / "extension" / "dist"
BACKEND = os.environ.get("SOCIALLENS_URL", "http://127.0.0.1:17800")


INSTANCE: str | None = None  # set once the test browser's extension connects; pins all requests to it


def http(method: str, path: str, body: dict | None = None, timeout: float = 40) -> tuple[int, dict]:
    req = urllib.request.Request(BACKEND + path, method=method)
    if INSTANCE:
        req.add_header("x-sociallens-instance", INSTANCE)
        req.add_header("x-sociallens-allow-anonymous", "1")  # the test browser is never logged in
    data = None
    if body is not None:
        if INSTANCE and isinstance(body.get("params"), dict):
            body = {**body, "params": {**body["params"], "_instance": INSTANCE}}
        req.add_header("content-type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def step(name: str) -> None:
    print(f"\n== {name}")


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def wait_for(pred, timeout: float, every: float = 0.5, what: str = ""):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            v = pred()
            if v:
                return v
        except Exception:  # noqa: BLE001
            pass
        time.sleep(every)
    raise SystemExit(f"timeout waiting for {what}")


def main() -> None:
    check(EXT_DIST.exists(), f"extension built at {EXT_DIST}")
    status, _ = http("GET", "/health")
    check(status == 200, "backend /health")
    profile = tempfile.mkdtemp(prefix="sociallens-e2e-")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            profile,
            channel="chromium",  # full Chromium in new headless mode; the headless shell has no extension support
            headless=not os.environ.get("HEADED"),
            args=[f"--disable-extensions-except={EXT_DIST}", f"--load-extension={EXT_DIST}"],
        )
        try:
            step("chromium + extension")
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20_000)
            check(sw.url.endswith("/background.js"), f"service worker {sw.url}")

            step("extension connects to backend")
            before = {c["id"] for c in http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"]}
            mine = wait_for(
                lambda: [c for c in http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"] if c["id"] not in before],
                30,
                what="test browser's extension to connect",
            )
            global INSTANCE
            INSTANCE = mine[-1]["id"]
            st = http("GET", "/api/v1/status")[1]["data"]
            check(st["extension"]["online"], f"online as {INSTANCE}, extension version {mine[-1]['extension_version']}, {len(st['extension']['connections'])} instance(s) total")
            check(st["extension"]["auth_method"] == "origin", f"authenticated by Origin header (fixed extension id), no token")

            step("echo via service worker")
            status, body = http("POST", "/api/v1/tasks/echo", {"payload": {"n": 1}, "instance": INSTANCE})
            check(status == 200 and body["data"]["via"] == "background", f"round trip: {body['data']}")

            step("bilibili: login gate")
            status, body = http("POST", "/api/v1/bilibili/echo", {"instance": INSTANCE})
            check(status == 401 and body["error"]["code"] == "not_logged_in", "fresh profile reported as not logged in")

            step("bilibili: page-level echo (opens a tab, needs network)")
            status, body = http("POST", "/api/v1/bilibili/echo", {"allow_anonymous": True, "instance": INSTANCE}, timeout=60)
            check(status == 200 and body.get("data", {}).get("via") == "page", f"page answered: {body}")
            tabs = wait_for(lambda: http("GET", "/api/v1/status")[1]["data"]["platforms"]["bilibili"]["tabs"], 10, what="tab.state broadcast")
            check(len(tabs) >= 1, f"status shows bilibili tabs {tabs}")

            step("bilibili: record mode + in-page fetch")
            http("POST", "/api/v1/bilibili/record", {"enabled": True})
            status, body = http(
                "POST",
                "/api/v1/bilibili/run",
                {"action": "fetch", "params": {"url": "https://api.bilibili.com/x/web-interface/nav", "allow_anonymous": True}},
                timeout=60,
            )
            check(status == 200, f"in-page fetch status {body.get('data', {}).get('status')}")
            nav = body["data"]["body"]
            check(isinstance(nav, dict) and "code" in nav, f"nav api answered code={nav.get('code') if isinstance(nav, dict) else nav}")
            raw = wait_for(lambda: [f for f in http("GET", "/api/v1/bilibili/raw")[1]["data"] if "nav" in f["file"]], 10, what="raw sample")
            check(bool(raw), f"raw archive has nav sample: {raw[0]['file']}")
            http("POST", "/api/v1/bilibili/record", {"enabled": False})

            step("bilibili: read_global")
            status, body = http("POST", "/api/v1/bilibili/run", {"action": "read_global", "params": {"path": "navigator.userAgent", "allow_anonymous": True}})
            check(status == 200 and "Chrome" in str(body["data"]), "read window.navigator.userAgent")

            step("bilibili: data routes (search -> post -> comments), anonymous")
            # Anonymous search occasionally comes back empty (soft risk control); retry a few times.
            for attempt in range(3):
                status, body = http("GET", "/api/v1/bilibili/search?keyword=python", timeout=60)
                if status == 200 and body["data"]["items"]:
                    break
                _, raw = http("POST", "/api/v1/bilibili/run", {"action": "search_posts", "params": {"keyword": "python", "allow_anonymous": True}, "raw": True}, timeout=60)
                d = (raw.get("data") or {}).get("data") or {}
                print(f"  info empty search: numResults={d.get('numResults')} numPages={d.get('numPages')} result_types={sorted({r.get('type') for r in (d.get('result') or [])})} keys={list(d.keys())[:8]} err={raw.get('error')}")
                time.sleep(4)
            check(status == 200 and body["data"]["items"], f"search returned {len(body.get('data', {}).get('items', []))} posts, cursor={bool(body.get('cursor'))} (attempt {attempt + 1})")
            bvid = body["data"]["items"][0]["id"]
            status, body = http("GET", f"/api/v1/bilibili/posts/{bvid}", timeout=60)
            check(status == 200 and body["data"]["id"] == bvid and body["data"]["media"], f"post {bvid}: {body.get('data', {}).get('title', '')[:40]}")
            status, body = http("GET", f"/api/v1/bilibili/posts/{bvid}/comments", timeout=60)
            check(status == 200 and body["data"]["items"] and body["data"]["items"][0]["post_id"] == bvid, f"{len(body.get('data', {}).get('items', []))} comments")
            status, body = http("GET", "/api/v1/bilibili/search?keyword=" + urllib.parse.quote("老番茄") + "&type=user", timeout=60)
            check(status == 200 and body["data"]["items"][0]["name"], f"user search: {body['data']['items'][0]['name']}")

            step("bilibili: navigate strategy + wait_capture")
            status, body = http(
                "POST",
                "/api/v1/bilibili/run",
                {
                    "action": "navigate",
                    "params": {"url": f"https://www.bilibili.com/video/{bvid}/", "capture_pattern": "/x/web-interface/", "allow_anonymous": True},
                },
                timeout=60,
            )
            if status == 423 and body.get("error", {}).get("code") == "captcha_required":
                print("  ok   navigate hit bilibili risk control (captcha_required) - expected for an anonymous profile, reported instead of timing out")
                http("POST", "/api/v1/bilibili/resume")
            else:
                check(status == 200 and "/x/web-interface/" in str(body.get("data", {}).get("url")), f"captured {body.get('data', {}).get('url')} (status {status}, error {body.get('error')})")

            print("\nALL PASSED")
        finally:
            ctx.close()
    shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
