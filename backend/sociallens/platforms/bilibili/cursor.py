"""Opaque pagination cursors: base64url of a small JSON dict of platform paging params."""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_cursor(params: dict[str, Any] | None) -> str | None:
    if not params:
        return None
    raw = json.dumps(params, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    pad = "=" * (-len(cursor) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + pad))
    except Exception:  # noqa: BLE001
        return {}
