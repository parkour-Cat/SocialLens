"""Record real B 站 responses as parser fixtures.

Runs each platform action through the running backend + a real extension in Playwright
Chromium (anonymous profile) and saves the raw payload to backend/tests/fixtures/bilibili/.
Re-run whenever the platform changes shape.

Usage: backend running, extension built, then
  uv run --project backend python scripts/sample_bilibili.py
Set LOGGED_IN=1 to skip actions that only work anonymously? (none currently) — kept simple.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
EXT_DIST = REPO / "extension" / "dist"
FIXTURES = REPO / "backend" / "tests" / "fixtures" / "bilibili"
BACKEND = os.environ.get("SOCIALLENS_URL", "http://127.0.0.1:17800")

# Ids for the detail actions are taken from the live search result so they always exist.
SAMPLES = [
    ("search_posts", {"keyword": "python 教程"}),
    ("search_users", {"keyword": "老番茄"}),
    ("get_post", {"id": "$bvid"}),
    ("get_comments", {"post_id": "$bvid"}),
    ("get_user", {"id": "$mid"}),
    ("get_user_posts", {"id": "$mid"}),
]


def http(method: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, dict]:
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


def capable_instances() -> list[dict]:
    try:
        conns = http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"]
    except Exception:  # noqa: BLE001
        return []
    return [c for c in conns if c.get("actions", {}).get("bilibili")]


def wait_capable(timeout=30) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = capable_instances()
        if found:
            return found
        time.sleep(0.5)
    raise SystemExit("no extension instance with bilibili actions came online")


def main() -> None:
    assert EXT_DIST.exists(), "build the extension first"
    assert http("GET", "/health")[0] == 200, "backend not running"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="sociallens-sample-")
    failures = 0
    http("POST", "/api/v1/bilibili/resume")
    before = {c["id"] for c in http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"]}
    existing = capable_instances()
    logged_in = [c for c in existing if c.get("platforms", {}).get("bilibili", {}).get("logged_in")]
    if logged_in and not os.environ.get("FORCE_CHROMIUM"):
        print(f"using already-connected logged-in instance {logged_in[0]['id']} (set FORCE_CHROMIUM=1 to launch a fresh Chromium instead)")
        ctx_manager = None
    else:
        print("launching anonymous Playwright Chromium; search actions may hit risk control without a login")
        ctx_manager = sync_playwright()
    pw = ctx_manager.__enter__() if ctx_manager else None
    ctx = None
    if pw:
        ctx = pw.chromium.launch_persistent_context(
            profile,
            channel="chromium",
            headless=not os.environ.get("HEADED"),
            args=[f"--disable-extensions-except={EXT_DIST}", f"--load-extension={EXT_DIST}"],
        )
    if True:
        try:
            wait_capable()
            pin = None
            if ctx:
                mine = [c for c in http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"] if c["id"] not in before]
                while not mine:
                    time.sleep(0.5)
                    mine = [c for c in http("GET", "/api/v1/status")[1]["data"]["extension"]["connections"] if c["id"] not in before]
                pin = mine[-1]["id"]
                print(f"pinned to test instance {pin}")
            elif logged_in:
                pin = logged_in[0]["id"]
            ids: dict[str, str] = {}
            for action, params in SAMPLES:
                params = {k: ids.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v for k, v in params.items()}
                status, body = http("POST", "/api/v1/bilibili/run", {"action": action, "params": {**params, "allow_anonymous": True, **({"_instance": pin} if pin else {})}, "raw": True})
                if status != 200:
                    failures += 1
                    print(f"  FAIL {action}: {body.get('error')}")
                    http("POST", "/api/v1/bilibili/resume")  # a 412 pauses the queue; keep sampling
                    continue
                if action == "search_posts":
                    first = next((r for r in body["data"]["data"]["result"] if r.get("type") == "video"), {})
                    ids["bvid"], ids["mid"] = str(first.get("bvid", "")), str(first.get("mid", ""))
                out = FIXTURES / f"{action}.json"
                out.write_text(json.dumps(body["data"], ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  ok   {action} -> {out.name} ({out.stat().st_size // 1024} KB)")
        finally:
            if ctx:
                ctx.close()
            if ctx_manager:
                ctx_manager.__exit__(None, None, None)
    shutil.rmtree(profile, ignore_errors=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
