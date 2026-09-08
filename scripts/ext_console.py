"""Debug helper: load the extension in Playwright Chromium, stream the service worker console,
optionally run one backend request. Usage:
  uv run --project backend python scripts/ext_console.py [seconds] [action] [json-params]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
EXT_DIST = REPO / "extension" / "dist"
BACKEND = os.environ.get("SOCIALLENS_URL", "http://127.0.0.1:17800")


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    action = sys.argv[2] if len(sys.argv) > 2 else None
    params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    profile = tempfile.mkdtemp(prefix="sociallens-dbg-")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            profile, channel="chromium", headless=not os.environ.get("HEADED"),
            args=[f"--disable-extensions-except={EXT_DIST}", f"--load-extension={EXT_DIST}"],
        )
        try:
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=20_000)
            sw.on("console", lambda m: print(f"[sw:{m.type}] {m.text}"))
            sw.evaluate("() => chrome.storage.local.set({verbose: true}).then(() => self.__sociallens.reconnect())")
            ctx.on("page", lambda pg: pg.on("console", lambda m: print(f"[page:{m.type}] {m.text}") if "SocialLens" in m.text else None))
            t0 = time.time()
            if action:
                # pin to this browser's instance so the user's own Chrome is never touched
                pin = None
                deadline = time.time() + 20
                while not pin and time.time() < deadline:
                    conns = json.loads(urllib.request.urlopen(f"{BACKEND}/api/v1/status").read())["data"]["extension"]["connections"]
                    fresh = [c for c in conns if c["last_pong_age_s"] < 5 and c["id"] != os.environ.get("SKIP_INSTANCE")]
                    pin = max(fresh, key=lambda c: int(c["id"][3:]))["id"] if fresh else None
                    time.sleep(0.5)
                print("pinned to", pin)
                req = urllib.request.Request(f"{BACKEND}/api/v1/bilibili/run", method="POST", data=json.dumps({"action": action, "params": {**params, "allow_anonymous": True, "_instance": pin}}).encode(), headers={"content-type": "application/json"})
                out = os.environ.get("RESULT_FILE")
                try:
                    with urllib.request.urlopen(req, timeout=90) as r:
                        data = r.read()
                        print("RESULT", r.status, data[:300])
                except urllib.error.HTTPError as e:
                    data = e.read()
                    print("RESULT", e.code, data[:300])
                if out:
                    Path(out).write_bytes(data)
            while time.time() - t0 < seconds:
                time.sleep(0.5)
        finally:
            ctx.close()
    shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
