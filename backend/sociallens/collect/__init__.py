"""Multi-page collection: one task that pages through a list action until `limit` items, the
site's end of list, `max_pages`, or an error. Each page is an ordinary platform task, so the
per-platform interval and page-load budget apply; a failure after N pages keeps the N pages
(status done, result.stopped_by = "error", result.error filled) instead of losing them.

Task.action = "collect"; task.result while running / when done:
  {"action", "params", "limit", "max_pages", "items": [...], "count", "pages", "complete",
   "stopped_by": "limit" | "no_more" | "max_pages" | "error" | null, "error": {...} | null, "kind"}
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from ..models.task import Task, TaskStatus
from ..platforms.registry import PlatformRegistry
from ..storage.db import Database
from ..tasks.manager import TaskManager

log = get_logger("collect")

LIST_ACTIONS: dict[str, str | None] = {
    # action -> cache kind (None: not cached, e.g. trending topics)
    "search_posts": "posts",
    "search_users": "users",
    "get_comments": "comments",
    "get_replies": "comments",
    "get_user_posts": "posts",
    "get_feed": "posts",
    "get_trending": "posts",
}
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_MAX_PAGES = 20
MAX_PAGES_CAP = 100


class CollectManager:
    def __init__(self, registry: PlatformRegistry, tasks: TaskManager, db: Database) -> None:
        self.registry = registry
        self.tasks = tasks
        self.db = db
        self._running: dict[str, asyncio.Task] = {}

    async def start(self, platform: str, action: str, params: dict[str, Any], limit: int | None, max_pages: int | None) -> Task:
        adapter = self.registry.get(platform)
        if adapter is None:
            raise SocialLensError(ErrorCode.UNKNOWN_PLATFORM, f"unknown platform: {platform}")
        if action not in LIST_ACTIONS:
            raise SocialLensError(ErrorCode.BAD_REQUEST, f"collect supports list actions only: {', '.join(LIST_ACTIONS)}")
        if adapter.capability(action) is None:
            raise SocialLensError(ErrorCode.UNSUPPORTED, f"{platform} does not support {action}")
        limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        max_pages = max(1, min(int(max_pages or DEFAULT_MAX_PAGES), MAX_PAGES_CAP))
        clean = {k: v for k, v in params.items() if v is not None and k != "cursor"}
        task = Task(platform=platform, action="collect", params={"action": action, "params": clean, "limit": limit, "max_pages": max_pages}, strategy="backend", timeout_ms=3600_000)
        task.result = {"action": action, "params": clean, "limit": limit, "max_pages": max_pages, "items": [], "count": 0, "pages": 0, "complete": False, "stopped_by": None, "error": None, "kind": LIST_ACTIONS[action]}
        self.tasks.register(task, cancel=lambda: self._cancel(task.id))
        self._running[task.id] = asyncio.create_task(self._run(task))
        return task

    async def wait(self, task: Task, timeout_s: float) -> Task:
        await self.tasks.wait(task.id, timeout_s)
        return task

    def list(self, platform: str | None, limit: int) -> list[Task]:
        return [t for t in self.tasks.list(platform, None, 500) if t.action == "collect"][:limit]

    async def _cancel(self, task_id: str) -> None:
        t = self._running.get(task_id)
        if t and not t.done():
            t.cancel()

    async def _run(self, task: Task) -> None:
        r = task.result
        platform, action, params = task.platform, r["action"], dict(r["params"])
        seen: set[str] = set()
        cursor: str | None = None
        try:
            task.status = TaskStatus.RUNNING
            self.tasks.save(task)
            while True:
                page = await self.tasks.run(platform, action, {**params, **({"cursor": cursor} if cursor else {})})
                data = page.result if isinstance(page.result, dict) else {}
                r["pages"] += 1
                if data.get("kind"):
                    r["kind"] = data["kind"] if data["kind"] != "topics" else None
                for it in data.get("items") or []:
                    key = str(it.get("id")) if isinstance(it, dict) and it.get("id") is not None else None
                    if key is not None and key in seen:
                        continue
                    if key is not None:
                        seen.add(key)
                    r["items"].append(it)
                    if len(r["items"]) >= r["limit"]:
                        break
                r["count"] = len(r["items"])
                r["total"] = data.get("total")
                cursor = data.get("cursor")
                if r["count"] >= r["limit"]:
                    r["stopped_by"] = "limit"
                elif not cursor or not data.get("items"):
                    r["stopped_by"], r["complete"] = "no_more", True
                elif r["pages"] >= r["max_pages"]:
                    r["stopped_by"] = "max_pages"
                self.tasks.save(task)
                if r["stopped_by"]:
                    break
            self._cache(platform, r)
            self.tasks.finish(task, TaskStatus.DONE, result=r)
            log.info("collect finished", task_id=task.id, platform=platform, action=action, count=r["count"], pages=r["pages"], stopped_by=r["stopped_by"])
        except asyncio.CancelledError:
            r["stopped_by"] = "cancelled"
            self._cache(platform, r)
            self.tasks.finish(task, TaskStatus.CANCELLED, result=r, error={"code": "cancelled", "message": "cancelled by client"})
        except SocialLensError as e:
            # Keep what was collected: the task is done with a partial result, the error is in it.
            r["stopped_by"], r["error"] = "error", e.to_dict()
            self._cache(platform, r)
            if r["items"]:
                self.tasks.finish(task, TaskStatus.DONE, result=r)
            else:
                self.tasks.finish(task, TaskStatus.FAILED, result=r, error=e.to_dict())
            log.warning("collect stopped by error", task_id=task.id, page=r["pages"] + 1, code=e.raw_code, message=e.message, kept=r["count"])
        except Exception as e:  # noqa: BLE001
            r["stopped_by"], r["error"] = "error", {"code": ErrorCode.INTERNAL, "message": repr(e)}
            self.tasks.finish(task, TaskStatus.FAILED if not r["items"] else TaskStatus.DONE, result=r, error=None if r["items"] else r["error"])
            log.error("collect crashed", task_id=task.id, error=repr(e))
        finally:
            self._running.pop(task.id, None)

    def _cache(self, platform: str, r: dict[str, Any]) -> None:
        if r.get("kind") and r["items"]:
            try:
                self.db.upsert_items(r["kind"], platform, r["items"])
            except Exception as e:  # noqa: BLE001
                log.warning("collect cache write failed", error=repr(e))
