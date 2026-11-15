"""Disk usage and retention.

What grows without bound: the tasks table (every finished task keeps its full result; the
items and queries tables already hold what users browse later), the health-probe log, record
mode captures under raw/, and upload chunks left behind by interrupted downloads. Those are
pruned on a schedule by default. The user's own data (cached posts / users / comments, query
history, metric snapshots, risk events) is kept unless they set a retention for it or clear it
from the console. Downloaded media is never touched.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError
from .db import Database

log = get_logger("retention")

STARTUP_DELAY_S = 120.0


@dataclass(frozen=True)
class _Table:
    table: str
    ts: str  # timestamp column (UTC ISO strings, comparable as text)
    size_expr: str  # approximate payload bytes per row
    where: str = ""  # extra condition rows must meet to be prunable


TABLES: dict[str, _Table] = {
    "tasks": _Table("tasks", "updated_at", "length(body)", "status IN ('done', 'failed', 'cancelled')"),
    "health": _Table("health", "checked_at", "length(body)"),
    "risk_events": _Table("risk_events", "at", "length(body)"),
    "queries": _Table("queries", "at", "length(params) + length(item_ids)"),
    "snapshots": _Table("item_snapshots", "at", "length(metrics)"),
    "items": _Table("items", "updated_at", "length(body)"),
}
DIRS = ("raw", "uploads")
TARGETS = (*TABLES, *DIRS)


def _cutoff(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _dir_usage(root: Path) -> dict[str, int]:
    files = size = 0
    if root.exists():
        for dirpath, _, names in os.walk(root):
            for n in names:
                try:
                    size += (Path(dirpath) / n).stat().st_size
                    files += 1
                except OSError:
                    pass
    return {"bytes": size, "files": files}


def _prune_dir(root: Path, days: float) -> tuple[int, int]:
    """Delete files older than `days` (by mtime), then empty directories. Returns (files, bytes)."""
    if not root.exists():
        return 0, 0
    limit = float("inf") if days <= 0 else time.time() - days * 86400
    files = freed = 0
    for dirpath, _, names in os.walk(root, topdown=False):
        d = Path(dirpath)
        for n in names:
            p = d / n
            try:
                st = p.stat()
                if st.st_mtime < limit:
                    p.unlink()
                    files += 1
                    freed += st.st_size
            except OSError:
                pass
        if d != root:
            try:
                d.rmdir()  # only succeeds when empty
            except OSError:
                pass
    return files, freed


class RetentionManager:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.interval_s = max(0.0, float(settings.prune_interval_h)) * 3600
        self.last: dict[str, Any] | None = None
        self._loop: asyncio.Task | None = None

    # ---- policy ------------------------------------------------------------

    def policy(self) -> dict[str, float]:
        """Configured retention in days per target; 0 = keep forever."""
        return {t: float(getattr(self.settings, f"retain_{t}_days")) for t in TARGETS}

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self.interval_s > 0 and self._loop is None:
            self._loop = asyncio.create_task(self._schedule())

    async def stop(self) -> None:
        if self._loop and not self._loop.done():
            self._loop.cancel()
        self._loop = None

    async def _schedule(self) -> None:
        try:
            await asyncio.sleep(STARTUP_DELAY_S)
            while True:
                try:
                    self.prune(source="schedule")
                except Exception as e:  # never let housekeeping take the backend down
                    log.error("scheduled prune failed", error=repr(e))
                await asyncio.sleep(self.interval_s)
        except asyncio.CancelledError:
            pass

    # ---- usage -------------------------------------------------------------

    def usage(self) -> dict[str, Any]:
        s = self.settings
        db_bytes = sum(p.stat().st_size for p in (s.db_path, Path(f"{s.db_path}-wal")) if p.exists())
        tables = {}
        for name, t in TABLES.items():
            row = self.db.conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM({t.size_expr}), 0) AS b, MIN({t.ts}) AS oldest FROM {t.table}").fetchone()
            tables[name] = {"rows": int(row["n"]), "bytes": int(row["b"]), "oldest": row["oldest"]}
        dirs = {name: _dir_usage(getattr(s, f"{name}_dir")) for name in ("downloads", "raw", "uploads", "logs")}
        return {
            "data_dir": str(s.data_dir),
            "db": {"path": str(s.db_path), "bytes": db_bytes},
            "tables": tables,
            "dirs": dirs,
            "policy": self.policy(),
            "prune_interval_h": s.prune_interval_h,
            "last_prune": self.last,
        }

    # ---- prune -------------------------------------------------------------

    def prune(self, older_than_days: dict[str, float] | None = None, vacuum: bool | None = None, source: str = "api") -> dict[str, Any]:
        """Delete what is older than the given days per target (default: the configured policy;
        a target at 0 in the policy is skipped, while an explicit 0 here means everything)."""
        if older_than_days is None:
            plan = {t: d for t, d in self.policy().items() if d > 0}
        else:
            unknown = sorted(set(older_than_days) - set(TARGETS))
            if unknown:
                raise SocialLensError(ErrorCode.BAD_REQUEST, f"unknown targets: {', '.join(unknown)}; valid: {', '.join(TARGETS)}")
            bad = [t for t, d in older_than_days.items() if d is None or d < 0]
            if bad:
                raise SocialLensError(ErrorCode.BAD_REQUEST, f"days must be >= 0: {', '.join(bad)}")
            plan = dict(older_than_days)

        db_before = self._db_bytes()
        removed: dict[str, int] = {}
        files_freed = 0
        for target, days in plan.items():
            if target in TABLES:
                t = TABLES[target]
                conds, args = ([t.where] if t.where else []), []
                if days > 0:  # 0 = everything, however recent
                    conds.append(f"{t.ts} < ?")
                    args.append(_cutoff(days))
                cur = self.db.conn.execute(f"DELETE FROM {t.table}" + (f" WHERE {' AND '.join(conds)}" if conds else ""), args)
                removed[target] = cur.rowcount
            else:
                n, b = _prune_dir(getattr(self.settings, f"{target}_dir"), days)
                removed[target] = n
                files_freed += b
        self.db.conn.commit()

        rows = sum(n for t, n in removed.items() if t in TABLES)
        do_vacuum = (rows > 0) if vacuum is None else vacuum
        if do_vacuum:
            self.db.conn.execute("VACUUM")
        result = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "older_than_days": plan,
            "removed": removed,
            "vacuumed": do_vacuum,
            "db_bytes_before": db_before,
            "db_bytes_after": self._db_bytes(),
            "files_bytes_freed": files_freed,
        }
        self.last = result
        log.info("prune", **{k: v for k, v in result.items() if k != "at"})
        return result

    def _db_bytes(self) -> int:
        p = self.settings.db_path
        return p.stat().st_size if p.exists() else 0
