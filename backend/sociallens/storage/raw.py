"""Raw response archive used by record mode and parse failures."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class RawStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def save(self, platform: str, capture: dict[str, Any], label: str | None = None) -> Path:
        now = datetime.now(timezone.utc)
        day_dir = self.root / _SAFE.sub("_", platform) / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        url = str(capture.get("url", ""))
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        stem = label or self._url_stem(url)
        name = f"{now.strftime('%H%M%S_%f')}_{stem}_{digest}.json"
        path = day_dir / name
        path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def list_day(self, platform: str, day: str | None = None) -> list[dict[str, Any]]:
        plat_dir = self.root / _SAFE.sub("_", platform)
        if not plat_dir.exists():
            return []
        days = [day] if day else sorted(p.name for p in plat_dir.iterdir() if p.is_dir())
        out = []
        for d in days:
            ddir = plat_dir / d
            if not ddir.exists():
                continue
            for f in sorted(ddir.glob("*.json")):
                out.append({"date": d, "file": f.name, "size": f.stat().st_size, "path": str(f)})
        return out

    @staticmethod
    def _url_stem(url: str) -> str:
        path = url.split("?", 1)[0]
        path = path.split("://", 1)[-1]
        parts = [p for p in path.split("/") if p]
        stem = "_".join(parts[-3:]) if parts else "root"
        return _SAFE.sub("_", stem)[:80]
