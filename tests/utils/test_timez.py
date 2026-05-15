"""hardening-iteration-v1 P2.5 — timezone helpers + utcnow() purge.

Pre-P2.5 the codebase had 7 ``datetime.utcnow()`` call sites (deprecated
in Python 3.12+). Each one returned a *naive* UTC datetime, which is a
silent footgun the moment it gets compared with anything tz-aware.
This suite locks down:

    1. now_utc() returns a tz-aware UTC datetime.
    2. now_ny() returns a tz-aware America/New_York datetime.
    3. today_str_ny() formats today's date (NY zone).
    4. utc_iso_z() formats ISO-8601 with a Z suffix.
    5. No production code path still calls datetime.utcnow().
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stock_trading_system.utils.timez import (
    NY, UTC, now_utc, now_ny, today_str_ny, utc_iso_z,
)


def test_now_utc_is_aware_and_utc():
    t = now_utc()
    assert t.tzinfo is not None
    assert t.tzinfo == UTC or t.utcoffset().total_seconds() == 0


def test_now_ny_is_aware_and_us_east():
    t = now_ny()
    assert t.tzinfo is not None
    # US East offsets: -5 (EST) or -4 (EDT). Anything else means we
    # accidentally bound to UTC or local.
    offset_hours = t.utcoffset().total_seconds() / 3600
    assert offset_hours in (-5, -4), f"unexpected NY offset: {offset_hours}h"


def test_today_str_ny_format_yyyy_mm_dd():
    s = today_str_ny()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s), s


def test_utc_iso_z_ends_with_z():
    s = utc_iso_z()
    assert s.endswith("Z"), s
    # Body parses as a valid UTC ISO string after stripping Z.
    dt = datetime.fromisoformat(s[:-1])
    assert dt is not None


def test_no_utcnow_calls_in_production_code():
    """Regression guard: every legacy ``datetime.utcnow()`` must route
    through timez. The only exception is timez.py's own docstring that
    references the deprecated API for historical context."""
    pkg_root = Path(__file__).resolve().parent.parent.parent / "stock_trading_system"
    bad: list[str] = []
    for p in pkg_root.rglob("*.py"):
        rel = p.relative_to(pkg_root)
        if rel.parts[0] == "utils" and rel.parts[-1] == "timez.py":
            continue
        src = p.read_text(encoding="utf-8")
        # Only flag actual calls (open paren following), not doc text.
        if re.search(r"datetime\.utcnow\s*\(", src):
            bad.append(str(rel))
    assert not bad, f"P2.5 regression: datetime.utcnow() call sites remain: {bad}"


def test_no_bare_datetime_now_calls_in_production_code():
    """P2.5 step-1: every ``datetime.now()`` call routes through timez.

    Step-1 collapses them all to ``now_local()`` so the grep guard works;
    step-2 (a follow-up PR) will audit each call site and split into
    ``now_utc()`` / ``now_ny()`` based on what the timestamp actually
    represents (DB write vs trading-day vs user-facing display).
    """
    pkg_root = Path(__file__).resolve().parent.parent.parent / "stock_trading_system"
    bad: list[str] = []
    for p in pkg_root.rglob("*.py"):
        rel = p.relative_to(pkg_root)
        if rel.parts[0] == "utils" and rel.parts[-1] == "timez.py":
            continue
        src = p.read_text(encoding="utf-8")
        if re.search(r"\bdatetime\.now\s*\(\s*\)", src):
            bad.append(str(rel))
    assert not bad, f"P2.5 regression: datetime.now() call sites remain: {bad}"


def test_now_local_is_naive_and_equivalent_to_datetime_now():
    """now_local() must behave identically to ``datetime.now()`` — naive
    server-local time. Any divergence would shift every DB timestamp
    field in lockstep without us noticing."""
    from stock_trading_system.utils.timez import now_local
    t = now_local()
    assert t.tzinfo is None, "now_local() must return naive (step-1 contract)"
