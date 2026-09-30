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
CREATE TABLE IF NOT EXISTS health (
    platform TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    state TEXT NOT NULL,         -- ok | broken | blocked | skipped
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_platform ON health(platform, checked_at);
CREATE TABLE IF NOT EXISTS risk_events (
    platform TEXT NOT NULL,
    at TEXT NOT NULL,
    code TEXT NOT NULL,          -- captcha_required | rate_limited
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_platform ON risk_events(platform, at);
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    platform TEXT NOT NULL,
    action TEXT NOT NULL,
    key TEXT NOT NULL,           -- keyword / post id / user id: what the query was about
    kind TEXT NOT NULL,          -- posts | users | comments
    source TEXT NOT NULL,        -- api | multi_search | collect
    first_page INTEGER NOT NULL, -- 0 for cursor continuations
    task_id TEXT,
    params TEXT NOT NULL,
    item_ids TEXT NOT NULL       -- JSON list, in result order
);
CREATE INDEX IF NOT EXISTS idx_queries_at ON queries(at);
CREATE TABLE IF NOT EXISTS item_snapshots (
    kind TEXT NOT NULL,
    platform TEXT NOT NULL,
    id TEXT NOT NULL,
    at TEXT NOT NULL,
    metrics TEXT NOT NULL        -- JSON, written only when it differs from the previous snapshot
);
CREATE INDEX IF NOT EXISTS idx_snapshots_item ON item_snapshots(kind, platform, id, at);
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

        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")  # snapshots and queries must order within a second
        rows = [(kind, platform, str(it["id"]), now, self._dumps(it)) for it in items if isinstance(it, dict) and it.get("id")]
        if not rows:
            return 0
        self.conn.executemany(
            """INSERT INTO items(kind, platform, id, updated_at, body) VALUES(?,?,?,?,?)
               ON CONFLICT(kind, platform, id) DO UPDATE SET updated_at=excluded.updated_at, body=excluded.body""",
            rows,
        )
        # Metric history: one snapshot per change, so a post seen ten times with the same counts
        # costs one row and a growing post keeps its curve.
        snaps = []
        for it in items:
            if not (isinstance(it, dict) and it.get("id") and isinstance(it.get("metrics"), dict)):
                continue
            metrics = {k: v for k, v in it["metrics"].items() if v is not None}
            if not metrics:
                continue
            last = self.conn.execute(
                "SELECT metrics FROM item_snapshots WHERE kind=? AND platform=? AND id=? ORDER BY at DESC, rowid DESC LIMIT 1", (kind, platform, str(it["id"]))
            ).fetchone()
            if last is None or json.loads(last["metrics"]) != metrics:
                snaps.append((kind, platform, str(it["id"]), now, json.dumps(metrics, ensure_ascii=False)))
        if snaps:
            self.conn.executemany("INSERT INTO item_snapshots(kind, platform, id, at, metrics) VALUES(?,?,?,?,?)", snaps)
        self.conn.commit()
        return len(rows)

    # ---- query history ------------------------------------------------------

    @staticmethod
    def query_key(params: dict) -> str:
        for k in ("keyword", "post_id", "user_id", "id", "comment_id"):
            if params.get(k):
                return str(params[k])
        return ""

    def save_query(self, platform: str, action: str, params: dict, kind: str, items: list[dict], *, source: str = "api", task_id: str | None = None, first_page: bool = True) -> int:
        from datetime import datetime, timezone

        clean = {k: v for k, v in params.items() if not str(k).startswith("_") and v is not None}
        ids = [str(it["id"]) for it in items if isinstance(it, dict) and it.get("id")]
        cur = self.conn.execute(
            "INSERT INTO queries(at, platform, action, key, kind, source, first_page, task_id, params, item_ids) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="microseconds"), platform, action, self.query_key(clean), kind, source, 1 if first_page else 0, task_id, json.dumps(clean, ensure_ascii=False), json.dumps(ids)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _query_row(r) -> dict:
        ids = json.loads(r["item_ids"])
        return {"id": r["id"], "at": r["at"], "platform": r["platform"], "action": r["action"], "key": r["key"], "kind": r["kind"], "source": r["source"], "first_page": bool(r["first_page"]), "task_id": r["task_id"], "params": json.loads(r["params"]), "count": len(ids)}

    def list_queries(self, platform: str | None = None, action: str | None = None, q: str | None = None, limit: int = 100, all_pages: bool = False) -> list[dict]:
        sql, clauses, args = "SELECT * FROM queries", [], []
        if not all_pages:
            clauses.append("first_page=1")
        if platform:
            clauses.append("platform=?")
            args.append(platform)
        if action:
            clauses.append("action=?")
            args.append(action)
        if q:
            clauses.append("key LIKE ?")
            args.append(f"%{q}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY at DESC, id DESC LIMIT ?"
        args.append(limit)
        return [self._query_row(r) for r in self.conn.execute(sql, args).fetchall()]

    def get_query(self, query_id: int) -> dict | None:
        """The query plus its items as they are cached now, each with `metrics_then` (the newest
        snapshot at or before the query) so old results still show the numbers of that day."""
        r = self.conn.execute("SELECT * FROM queries WHERE id=?", (query_id,)).fetchone()
        if r is None:
            return None
        out = self._query_row(r)
        items = []
        for item_id in json.loads(r["item_ids"]):
            body = self.get_item(out["kind"], out["platform"], item_id)
            if body is None:
                continue
            snap = self.conn.execute(
                "SELECT metrics FROM item_snapshots WHERE kind=? AND platform=? AND id=? AND at<=? ORDER BY at DESC, rowid DESC LIMIT 1", (out["kind"], out["platform"], item_id, out["at"])
            ).fetchone()
            items.append({**body, "metrics_then": json.loads(snap["metrics"]) if snap else None})
        out["items"] = items
        return out

    def item_history(self, kind: str, platform: str, item_id: str, limit: int = 200) -> list[dict]:
        """Oldest first."""
        rows = self.conn.execute("SELECT at, metrics FROM item_snapshots WHERE kind=? AND platform=? AND id=? ORDER BY at ASC, rowid ASC LIMIT ?", (kind, platform, item_id, limit)).fetchall()
        return [{"at": r["at"], "metrics": json.loads(r["metrics"])} for r in rows]

    def save_health(self, rec: dict) -> None:
        self.conn.execute("INSERT INTO health (platform, checked_at, state, body) VALUES (?, ?, ?, ?)", (rec["platform"], rec["checked_at"], rec["state"], json.dumps(rec, ensure_ascii=False)))
        self.conn.commit()

    def health_history(self, platform: str, limit: int = 50) -> list[dict]:
        """Newest first."""
        rows = self.conn.execute("SELECT body FROM health WHERE platform=? ORDER BY checked_at DESC, rowid DESC LIMIT ?", (platform, limit)).fetchall()
        return [json.loads(r["body"]) for r in rows]

    def save_risk_event(self, ev: dict) -> None:
        self.conn.execute("INSERT INTO risk_events (platform, at, code, body) VALUES (?, ?, ?, ?)", (ev["platform"], ev["at"], ev["code"], json.dumps(ev, ensure_ascii=False)))
        self.conn.commit()

    def risk_events(self, platform: str | None = None, limit: int = 100) -> list[dict]:
        """Newest first."""
        sql, args = "SELECT body FROM risk_events", []
        if platform:
            sql += " WHERE platform=?"
            args.append(platform)
        sql += " ORDER BY at DESC, rowid DESC LIMIT ?"
        args.append(limit)
        return [json.loads(r["body"]) for r in self.conn.execute(sql, args).fetchall()]

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
