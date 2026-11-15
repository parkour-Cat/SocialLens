"""Committed fixtures must be scrubbed copies (scripts/scrub_fixtures.py), never raw recordings.

A last line of defence for logged-in platforms: no login cookie names, tokens or auth headers
anywhere in backend/tests/fixtures/, and every platform there has scrub rules.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
SCRUB = TESTS.parent.parent / "scripts" / "scrub_fixtures.py"

CREDENTIALS = re.compile(
    r"SESSDATA|bili_jct|DedeUserID|web_session|sessionid|passport_csrf|sid_guard|csrftoken|ct0|auth_token"
    r"|\"authorization\"|\"cookie\"|\"set-cookie\"|access_token|refresh_token|x-csrf-token",
    re.I,
)

FILES = sorted(FIXTURES.rglob("*.json")) if FIXTURES.exists() else []


def _rules() -> set[str]:
    spec = importlib.util.spec_from_file_location("scrub_fixtures", SCRUB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up here
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return set(mod.RULES)


def test_every_fixture_platform_has_scrub_rules():
    platforms = {p.name for p in FIXTURES.iterdir() if p.is_dir()} if FIXTURES.exists() else set()
    assert platforms <= _rules(), f"fixtures without scrub rules: {sorted(platforms - _rules())}"


@pytest.mark.parametrize("path", FILES, ids=[str(p.relative_to(FIXTURES)) for p in FILES])
def test_no_credentials_in_fixture(path: Path):
    hits = sorted({m.group(0) for m in CREDENTIALS.finditer(path.read_text(encoding="utf-8"))})
    assert not hits, f"{path.relative_to(FIXTURES)} contains {hits}"
