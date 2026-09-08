"""SQLite persistence. Stage 0 only stores tasks; data tables come with the first platform."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..models.task import Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_platform_status ON tasks(platform, status);
CREATE TABLE IF NOT EXISTS items (
    kind TEXT NOT NULL,          -- posts | users | comments
    platform TEXT NOT NULL,
    id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (kind, platform, id)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def save_task(self, task: Task) -> None:
        self.conn.execute(
            """INSERT INTO tasks(id, platform, action, status, created_at, updated_at, body)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                   updated_at=excluded.updated_at, body=excluded.body""",
            (
                task.id,
                task.platform,
                task.action,
                task.status.value,
                task.created_at,
                task.updated_at,
                task.model_dump_json(),
            ),
        )
        self.conn.commit()

    def get_task(self, task_id: str) -> Task | None:
        row = self.conn.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.model_validate_json(row["body"]) if row else None

    def list_tasks(self, platform: str | None = None, status: str | None = None, limit: int = 100) -> list[Task]:
        sql = "SELECT body FROM tasks"
        clauses, args = [], []
        if platform:
            clauses.append("platform=?")
            args.append(platform)
        if status:
            clauses.append("status=?")
            args.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        rows = self.conn.execute(sql, args).fetchall()
        return [Task.model_validate_json(r["body"]) for r in rows]

    def count_tasks(self, platform: str, status: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE platform=? AND status=?", (platform, status)
        ).fetchone()
        return int(row["n"])

    # ---- normalized items cache -------------------------------------------

    def upsert_items(self, kind: str, platform: str, items: list[dict]) -> int:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [(kind, platform, str(it["id"]), now, self._dumps(it)) for it in items if isinstance(it, dict) and it.get("id")]
        if not rows:
            return 0
        self.conn.executemany(
            """INSERT INTO items(kind, platform, id, updated_at, body) VALUES(?,?,?,?,?)
               ON CONFLICT(kind, platform, id) DO UPDATE SET updated_at=excluded.updated_at, body=excluded.body""",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_item(self, kind: str, platform: str, item_id: str) -> dict | None:
        row = self.conn.execute("SELECT body FROM items WHERE kind=? AND platform=? AND id=?", (kind, platform, item_id)).fetchone()
        return json.loads(row["body"]) if row else None

    def list_items(self, kind: str, platform: str | None = None, limit: int = 100) -> list[dict]:
        sql, args = "SELECT body FROM items WHERE kind=?", [kind]
        if platform:
            sql += " AND platform=?"
            args.append(platform)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [json.loads(r["body"]) for r in self.conn.execute(sql, args).fetchall()]

    @staticmethod
    def _dumps(obj) -> str:
        return json.dumps(obj, ensure_ascii=False)
