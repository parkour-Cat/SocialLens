"""Platform health checks: one cheap probe per platform, on demand and on a schedule, so a site
change is noticed before the user needs that platform, not when a query times out.

A probe is the platform's cheapest read-only action with fixed params (see PROBES). Its outcome
is classified, not just pass/fail:

  ok       the action returned data
  broken   it failed in a way that points at our code or the site (timeout, parse_error,
           extension_error, unsupported, internal, not_found, or an empty list)
  blocked  the environment stopped it (not signed in, extension offline, captcha, rate limit):
           nothing to fix in the code, the platform simply cannot be checked right now
  skipped  the platform has no probe (视频号 has no public web surface)

Every result is appended to the `health` table; the summary reports each platform's latest state
plus `broken_since` (start of the current non-ok streak) and `last_ok_at`, so the overview page
can say "failing since 9-17 14:03". The scheduled run is one Task (platform `_system`, action
`health`) so it shows up in the task list like collect / download.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from ..models.task import Task, TaskStatus
from ..platforms.registry import PlatformRegistry
from ..storage.db import Database
from ..tasks.manager import TaskManager
from ..ws.hub import ExtensionHub

log = get_logger("health")

# platform -> (action, params). Prefer a list the site renders without any input (trending / home
# feed): no ids to go stale, one page load, and an empty answer is itself a signal.
PROBES: dict[str, tuple[str, dict[str, Any]]] = {
    "bilibili": ("get_trending", {}),
    "xiaohongshu": ("get_feed", {}),
    "douyin": ("get_trending", {}),
    "kuaishou": ("get_feed", {}),
    "weixin_mp": ("search_users", {"keyword": "人民日报"}),
    "youtube": ("get_trending", {}),
    "x": ("get_trending", {}),
    "reddit": ("get_trending", {}),
    "zhihu": ("get_trending", {}),
    "tiktok": ("get_feed", {}),
    "instagram": ("get_feed", {}),
    "toutiao": ("get_feed", {}),
    "linkedin": ("get_feed", {}),
}

BLOCKED_CODES = {ErrorCode.NOT_LOGGED_IN, ErrorCode.EXTENSION_OFFLINE, ErrorCode.CAPTCHA_REQUIRED, ErrorCode.RATE_LIMITED}
PROBE_TIMEOUT_S = 90.0
MAX_PARALLEL = 4  # tabs opening at once; more made content scripts miss their 20 s window
STARTUP_GRACE_S = 120.0  # let the extension reconnect before the first scheduled run


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify(error: dict[str, Any] | None, items: int | None) -> str:
    """State of one probe from its error (None on success) and item count (None for non-lists)."""
    if error is None:
        return "broken" if items == 0 else "ok"
    code = str(error.get("code") or "")
    return "blocked" if code in {c.value for c in BLOCKED_CODES} else "broken"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Latest state of one platform from its history (newest first): adds broken_since / last_ok_at."""
    if not rows:
        return None
    latest = dict(rows[0])
    streak_start = None
    last_ok = None
    for r in rows:
        if r["state"] == "ok":
            last_ok = r["checked_at"]
            break
        streak_start = r["checked_at"]
    latest["broken_since"] = streak_start if latest["state"] in ("broken", "blocked") else None
    latest["last_ok_at"] = last_ok
    return latest


class HealthManager:
    def __init__(self, registry: PlatformRegistry, tasks: TaskManager, hub: ExtensionHub, db: Database, interval_min: float) -> None:
        self.registry = registry
        self.tasks = tasks
        self.hub = hub
        self.db = db
        self.interval_s = max(0.0, float(interval_min)) * 60
        self._loop: asyncio.Task | None = None
        self._current: Task | None = None
        self._runner: asyncio.Task | None = None
        self._started = time.monotonic()

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self.interval_s > 0 and self._loop is None:
            self._loop = asyncio.create_task(self._schedule())

    async def stop(self) -> None:
        for t in (self._loop, self._runner):
            if t and not t.done():
                t.cancel()
        self._loop = self._runner = None

    async def _schedule(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                if time.monotonic() - self._started < STARTUP_GRACE_S or not self.hub.online or self._current:
                    continue
                if self._age_s() >= self.interval_s:
                    log.info("scheduled health check", interval_min=self.interval_s / 60)
                    self.check()
        except asyncio.CancelledError:
            pass

    def _age_s(self) -> float:
        newest = max((s["checked_at"] for s in self.summary()["platforms"].values() if s and s.get("checked_at")), default=None)
        if not newest:
            return float("inf")
        return (datetime.now(timezone.utc) - datetime.fromisoformat(newest)).total_seconds()

    # ---- runs --------------------------------------------------------------

    @property
    def running(self) -> Task | None:
        return self._current

    def check(self, platforms: list[str] | None = None) -> Task:
        """Start a check (all probed platforms by default); returns its Task. A run already in
        progress is returned instead of starting a second one."""
        if self._current is not None:
            return self._current
        ids = [p for p in (platforms or list(PROBES)) if self.registry.get(p) is not None]
        task = Task(platform="_system", action="health", params={"platforms": ids}, strategy="backend", timeout_ms=int(PROBE_TIMEOUT_S * 1000) + 30_000)
        task.result = {"platforms": ids, "results": [], "done": 0}
        self.tasks.register(task, cancel=self._cancel)
        self._current = task
        self._runner = asyncio.create_task(self._run(task))
        return task

    async def _cancel(self) -> None:
        if self._runner and not self._runner.done():
            self._runner.cancel()

    async def _run(self, task: Task) -> None:
        r = task.result
        try:
            task.status = TaskStatus.RUNNING
            self.tasks.save(task)
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def limited(p: str) -> dict[str, Any]:
                async with sem:
                    return await self.probe(p)

            results = await asyncio.gather(*(limited(p) for p in r["platforms"]))
            r["results"] = list(results)
            r["done"] = len(results)
            self.tasks.finish(task, TaskStatus.DONE, result=r)
            states = {s: sum(1 for x in results if x["state"] == s) for s in ("ok", "broken", "blocked", "skipped")}
            log.info("health check finished", task_id=task.id, **states)
        except asyncio.CancelledError:
            self.tasks.finish(task, TaskStatus.CANCELLED, result=r, error={"code": "cancelled", "message": "cancelled"})
        except Exception as e:  # noqa: BLE001
            self.tasks.finish(task, TaskStatus.FAILED, result=r, error={"code": ErrorCode.INTERNAL.value, "message": repr(e)})
        finally:
            self._current = None

    async def probe(self, platform: str) -> dict[str, Any]:
        """Run one platform's probe, record and return the outcome."""
        rec: dict[str, Any] = {"platform": platform, "checked_at": _now(), "action": None, "state": "skipped", "code": None, "message": None, "items": None, "elapsed_ms": 0}
        probe = PROBES.get(platform)
        if probe is None or self.registry.get(platform) is None:
            rec["message"] = "no probe for this platform"
        elif not self.hub.online:
            rec.update(action=probe[0], state="blocked", code=ErrorCode.EXTENSION_OFFLINE.value, message="extension is not connected")
        elif self.hub.tab_states.get(platform, {}).get("logged_in") is False:
            # Probing an anonymous session would only measure the login wall; skip the page load.
            rec.update(action=probe[0], state="blocked", code=ErrorCode.NOT_LOGGED_IN.value, message="not signed in")
        else:
            action, params = probe
            rec["action"] = action
            t0 = time.monotonic()
            try:
                self.tasks.note_context(platform, "health")
                task = await self.tasks.run(platform, action, dict(params), timeout_s=PROBE_TIMEOUT_S)
                data = task.result if isinstance(task.result, dict) else {}
                items = len(data.get("items") or []) if "items" in data else None
                rec.update(state=classify(None, items), items=items, message=None if items != 0 else "empty list")
            except SocialLensError as e:
                rec.update(state=classify(e.to_dict(), None), code=e.raw_code, message=e.message[:300])
            except Exception as e:  # noqa: BLE001
                rec.update(state="broken", code=ErrorCode.INTERNAL.value, message=repr(e)[:300])
            rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        self.db.save_health(rec)
        if rec["state"] in ("broken", "blocked"):
            log.warning("health probe not ok", platform=platform, state=rec["state"], code=rec["code"], message=rec["message"])
        return rec

    # ---- read --------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for pid in self.registry.ids():
            out[pid] = summarize(self.db.health_history(pid, 50))
        return {"platforms": out, "interval_min": self.interval_s / 60, "running": self._current.id if self._current else None, "probes": {p: a for p, (a, _) in PROBES.items()}}
