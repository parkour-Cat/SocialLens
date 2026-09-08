"""Per-platform task queues with rate limiting.

Every data fetch is a Task: REST creates it, a per-platform worker dispatches it to the
extension one at a time with the platform's rate limit, the adapter parses the raw result.
"""

from __future__ import annotations

import asyncio
from collections import deque
import random
import time
from typing import Any, Awaitable, Callable

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from ..models.task import Task, TaskStatus
from ..platforms.base import Capability
from ..platforms.registry import PlatformRegistry
from ..storage.db import Database
from ..ws.hub import ExtensionHub

log = get_logger("task")

# Actions every platform tab can execute without declaring them (see extension/src/page).
GENERIC_ACTIONS: dict[str, Capability] = {
    "echo": Capability("echo", "call", "Round-trip through the platform tab", 15000),
    "fetch": Capability("fetch", "call", "fetch(url) inside the page with the page's cookies", 30000),
    "wait_capture": Capability("wait_capture", "call", "Wait for a captured response whose URL matches a pattern", 30000),
    "read_global": Capability("read_global", "call", "Read a JSON-serialisable window.* global", 10000),
    "navigate": Capability("navigate", "navigate", "Open params.url in a temporary tab; return the first captured response matching params.capture_pattern, or run params.page_action there", 45000),
    "scroll_capture": Capability("scroll_capture", "call", "Scroll the page (or params.scroll_selector) until a new response matching params.pattern is captured", 30000),
    "dom_probe": Capability("dom_probe", "call", "Dev: page title, visibility, scrollable containers, recent captured URLs", 10000),
    "list_captures": Capability("list_captures", "call", "Dev: every captured response matching params.pattern (url, ts, size; params.body_chars adds a body head)", 10000),
    "find_scripts": Capability("find_scripts", "call", "Inline JSON script/code blocks whose text contains params.contains (server-rendered state)", 15000),
    "read_element": Capability("read_element", "call", "Read a DOM element (params.selector) text/attr, decode json | uri-json", 15000),
    "click": Capability("click", "call", "Click a DOM element (params.selector); the site's own handlers run", 15000),
    "type": Capability("type", "call", "Type params.text into params.selector like a user; params.submit presses Enter", 15000),
}


class _PlatformQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Task] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        self.last_dispatch: float = 0.0
        self.paused_until: float = 0.0
        self.running: Task | None = None
        self.page_loads: deque[float] = deque()  # monotonic times of recent fresh page loads
        self.budget_wait_until: float = 0.0

    def prune_page_loads(self, window_s: float) -> None:
        cutoff = time.monotonic() - window_s
        while self.page_loads and self.page_loads[0] < cutoff:
            self.page_loads.popleft()

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "pending": self.queue.qsize(),
            "running": self.running.id if self.running else None,
            "page_loads_in_window": len(self.page_loads),
            "budget_wait_s": max(0.0, round(self.budget_wait_until - now, 1)),
            "paused_for_s": round(self.paused_until - now, 1) if self.paused_until > now else 0,
        }


class TaskManager:
    def __init__(
        self,
        hub: ExtensionHub,
        registry: PlatformRegistry,
        db: Database,
        default_timeout_s: float,
        pause_on_rate_limit_s: float,
    ):
        self.hub = hub
        self.registry = registry
        self.db = db
        self.default_timeout_s = default_timeout_s
        self.pause_on_rate_limit_s = pause_on_rate_limit_s
        self._queues: dict[str, _PlatformQueue] = {}
        self._tasks: dict[str, Task] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._external_cancel: dict[str, Callable[[], Awaitable[None]]] = {}

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        for adapter in self.registry.all_including_system():
            self._ensure_queue(adapter.id)

    async def stop(self) -> None:
        for q in self._queues.values():
            if q.worker:
                q.worker.cancel()
        await asyncio.gather(*(q.worker for q in self._queues.values() if q.worker), return_exceptions=True)

    def _ensure_queue(self, platform: str) -> _PlatformQueue:
        q = self._queues.get(platform)
        if q is None:
            q = _PlatformQueue()
            q.worker = asyncio.create_task(self._worker(platform, q), name=f"worker:{platform}")
            self._queues[platform] = q
        return q

    def status(self) -> dict[str, Any]:
        return {pid: q.status() for pid, q in self._queues.items()}

    def resume(self, platform: str) -> None:
        """Clear a rate-limit / captcha pause after the user dealt with it in the browser."""
        q = self._queues.get(platform)
        if q:
            q.paused_until = 0.0

    # ---- submission --------------------------------------------------------

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id) or self.db.get_task(task_id)

    def list(self, platform: str | None, status: str | None, limit: int = 100) -> list[Task]:
        return self.db.list_tasks(platform, status, limit)

    async def submit(self, platform: str, action: str, params: dict[str, Any], timeout_s: float | None = None, parse: bool = True) -> Task:
        adapter = self.registry.get(platform)
        if adapter is None:
            raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {platform}")
        cap = adapter.capability(action) or GENERIC_ACTIONS.get(action)
        if cap is None:
            raise SocialLensError(ErrorCode.UNSUPPORTED, f"{platform} does not support {action}")
        if not self.hub.online:
            raise SocialLensError(ErrorCode.EXTENSION_OFFLINE, "extension is not connected")

        timeout_ms = int((timeout_s or cap.timeout_ms / 1000) * 1000)
        built = adapter.build_params(action, await adapter.prepare(action, params))
        strategy = built.pop("_strategy", None) or cap.strategy  # adapters may switch per call (cursor continuation)
        task = Task(
            platform=platform,
            action=action,
            params=built,
            strategy=strategy,
            timeout_ms=timeout_ms,
            parse=parse,
        )
        self._tasks[task.id] = task
        self._done[task.id] = asyncio.Event()
        self.db.save_task(task)
        self._ensure_queue(platform).queue.put_nowait(task)
        log.info("task queued", task_id=task.id, platform=platform, action=action)
        return task

    async def run(self, platform: str, action: str, params: dict[str, Any], timeout_s: float | None = None, parse: bool = True) -> Task:
        """Submit and wait for completion. Raises SocialLensError on failure."""
        task = await self.submit(platform, action, params, timeout_s, parse)
        wait_s = task.timeout_ms / 1000 + 5
        try:
            await asyncio.wait_for(self._done[task.id].wait(), timeout=wait_s)
        except asyncio.TimeoutError:
            # A task the caller gave up on must not run later and burn the page-load budget: drop it
            # while it is still queued (a running one is left to finish so its tab stays reusable).
            if task.status == TaskStatus.QUEUED:
                await self.cancel(task.id)
                raise SocialLensError(ErrorCode.TIMEOUT, f"task {task.id} was still queued after {wait_s}s and was cancelled: {self._queue_reason(platform)}")
            raise SocialLensError(ErrorCode.TIMEOUT, f"task {task.id} did not finish in {wait_s}s")
        if task.status == TaskStatus.FAILED and task.error:
            raise SocialLensError(task.error.get("code", ErrorCode.INTERNAL), task.error.get("message", ""), task.error.get("details"))
        return task

    def _queue_reason(self, platform: str) -> str:
        """Why a queued task has not started: page-load budget, a pause, or simply tasks ahead of it."""
        q = self._queues.get(platform)
        adapter = self.registry.get(platform)
        if not q:
            return "no queue for this platform"
        now = time.monotonic()
        ahead = q.queue.qsize()
        if q.paused_until > now:
            return f"the {platform} queue is paused for another {q.paused_until - now:.0f}s ({ahead} tasks ahead)"
        if q.budget_wait_until > now and adapter:
            rate = adapter.rate_limit
            return f"waiting for the page-load budget of {platform} ({rate.page_loads} fresh page loads per {rate.window_s:.0f}s); a slot frees in ~{q.budget_wait_until - now:.0f}s and {ahead} tasks are ahead"
        return f"{ahead} tasks are ahead in the {platform} queue" + (f" (the running one is {q.running.action})" if q.running else "")

    # ---- tasks executed outside the extension queue (downloads) -------------

    def register(self, task: Task, cancel: Callable[[], Awaitable[None]] | None = None) -> None:
        """Track a task that some other component runs (e.g. the download pipeline)."""
        self._tasks[task.id] = task
        self._done[task.id] = asyncio.Event()
        if cancel:
            self._external_cancel[task.id] = cancel
        self.db.save_task(task)

    def save(self, task: Task) -> None:
        task.touch()
        self.db.save_task(task)

    def finish(self, task: Task, status: TaskStatus, result: Any = None, error: dict | None = None) -> None:
        self._external_cancel.pop(task.id, None)
        self._finish(task, status, result, error)

    async def wait(self, task_id: str, timeout_s: float) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise SocialLensError(ErrorCode.NOT_FOUND, f"task {task_id} not found")
        ev = self._done.get(task_id)
        if ev and task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            try:
                await asyncio.wait_for(ev.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                pass  # caller reads task.status
        return task

    async def cancel(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise SocialLensError(ErrorCode.NOT_FOUND, f"task {task_id} not found")
        if task.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return task
        hook = self._external_cancel.pop(task_id, None)
        if hook:
            await hook()
            return task
        if task.status == TaskStatus.RUNNING:
            await self.hub.cancel(task.id)
        self._finish(task, TaskStatus.CANCELLED, error={"code": "cancelled", "message": "cancelled by client"})
        return task

    # ---- worker ------------------------------------------------------------

    async def _worker(self, platform: str, q: _PlatformQueue) -> None:
        adapter = self.registry.get(platform)
        rate = adapter.rate_limit if adapter else None
        while True:
            task = await q.queue.get()
            if task.status == TaskStatus.CANCELLED:
                continue
            try:
                await self._throttle(q, rate, task)
                await self._execute(task, q)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("worker error", task_id=task.id, error=repr(e))
                self._finish(task, TaskStatus.FAILED, error={"code": ErrorCode.INTERNAL, "message": repr(e)})

    @staticmethod
    def _is_page_load(task: Task) -> bool:
        """A navigate task that opens a fresh document (cursor continuations run in the kept tab)."""
        return task.strategy == "navigate" and task.params.get("_tab") is None and bool(task.params.get("url"))

    async def _throttle(self, q: _PlatformQueue, rate, task: Task | None = None) -> None:
        now = time.monotonic()
        if q.paused_until > now:
            await asyncio.sleep(q.paused_until - now)
        if rate and rate.interval_s > 0:
            wait = q.last_dispatch + rate.interval_s + random.uniform(0, rate.jitter_s) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        if rate and task is not None and self._is_page_load(task) and rate.page_loads > 0:
            q.prune_page_loads(rate.window_s)
            if len(q.page_loads) >= rate.page_loads:
                wait = q.page_loads[0] + rate.window_s - time.monotonic()
                if wait > 0:
                    q.budget_wait_until = time.monotonic() + wait
                    log.warning("page-load budget reached, task waits", platform=task.platform, task_id=task.id, budget=rate.page_loads, window_s=rate.window_s, wait_s=round(wait, 1))
                    await asyncio.sleep(wait)
                    q.budget_wait_until = 0.0
                    q.prune_page_loads(rate.window_s)
            q.page_loads.append(time.monotonic())

    async def _execute(self, task: Task, q: _PlatformQueue) -> None:
        adapter = self.registry.get(task.platform)
        task.status = TaskStatus.RUNNING
        task.touch()
        q.running = task
        q.last_dispatch = time.monotonic()
        self.db.save_task(task)
        log.info("task dispatched", task_id=task.id, platform=task.platform, action=task.action)
        started = time.monotonic()
        try:
            raw = await self.hub.dispatch(
                {
                    "id": task.id,
                    "platform": task.platform,
                    "action": task.action,
                    "params": task.params,
                    "strategy": task.strategy,
                    "timeout_ms": task.timeout_ms,
                },
                timeout_s=task.timeout_ms / 1000,
            )
            try:
                if adapter and task.parse:
                    pw = getattr(adapter, "parse_with_params", None)
                    result = pw(task.action, raw, task.params) if pw else adapter.parse(task.action, raw)
                else:
                    result = raw
            except Exception as e:  # noqa: BLE001
                raise SocialLensError(ErrorCode.PARSE_ERROR, f"parse failed: {e!r}", {"raw": raw})
            self._finish(task, TaskStatus.DONE, result=result)
            log.info("task done", task_id=task.id, elapsed_ms=int((time.monotonic() - started) * 1000))
        except SocialLensError as e:
            if e.code in (ErrorCode.RATE_LIMITED, ErrorCode.CAPTCHA_REQUIRED):
                q.paused_until = time.monotonic() + self.pause_on_rate_limit_s
                log.warning("platform queue paused", platform=task.platform, reason=e.code, seconds=self.pause_on_rate_limit_s)
            self._finish(task, TaskStatus.FAILED, error=e.to_dict())
            log.warning("task failed", task_id=task.id, code=e.raw_code, message=e.message)
        finally:
            q.running = None

    def _finish(self, task: Task, status: TaskStatus, result: Any = None, error: dict | None = None) -> None:
        task.status = status
        task.result = result
        task.error = error
        task.touch()
        self.db.save_task(task)
        ev = self._done.get(task.id)
        if ev:
            ev.set()
