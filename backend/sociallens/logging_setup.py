"""JSON-lines logging to stdout and data/logs/backend.log."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ExtraAdapter(logging.LoggerAdapter):
    """logger.info("msg", task_id=...) -> structured fields."""

    def process(self, msg, kwargs):
        fields = {k: v for k, v in kwargs.items() if k not in ("exc_info", "stack_info", "stacklevel")}
        for k in fields:
            kwargs.pop(k)
        kwargs["extra"] = {"extra": fields}
        return msg, kwargs


def get_logger(name: str) -> ExtraAdapter:
    return ExtraAdapter(logging.getLogger(name), {})


def setup_logging(level: str, logs_dir: Path) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = JsonFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    logs_dir.mkdir(parents=True, exist_ok=True)
    file = logging.FileHandler(logs_dir / "backend.log", encoding="utf-8")
    file.setFormatter(fmt)
    root.addHandler(file)

    logging.getLogger("uvicorn.access").setLevel("WARNING")
