from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_task_id() -> str:
    return uuid.uuid4().hex[:16]


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(BaseModel):
    id: str = Field(default_factory=new_task_id)
    platform: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "call"
    timeout_ms: int = 30000
    parse: bool = True  # False = return the raw extension payload (dev / sampling)
    status: TaskStatus = TaskStatus.QUEUED
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    result: Any = None
    error: dict[str, Any] | None = None

    def touch(self) -> None:
        self.updated_at = _now()

    def public(self) -> dict[str, Any]:
        return self.model_dump()
