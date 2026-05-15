"""Timezone-aware datetime helpers.

hardening-iteration-v1 P2.5: this module is the canonical entry-point
for "current time" inside the codebase. Two reasons it exists:

1. ``datetime.utcnow()`` is deprecated in Python 3.12+ — every legacy
   call must move to ``datetime.now(timezone.utc)``. ``now_utc()`` is
   the rename target.

2. The system mixes UTC (DB timestamps, audit logs, API contracts) and
   US market time (snapshot dates, trading-day rollovers). Naming each
   helper for its zone makes the intent obvious at the call site and
   stops "datetime.now() with no tzinfo" from accidentally drifting
   between UTC and server-local.

Use ``now_utc()`` for everything machine-facing (DB rows, audit logs,
JSON timestamps, ISO strings). Use ``now_ny()`` / ``today_str_ny()``
when the value drives a *trading* decision — last close, EOD cutoff,
daily snapshot date.

This module imports stdlib only (``datetime`` + ``zoneinfo``); no
project deps so it's import-safe from anywhere including tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def now_utc() -> datetime:
    """Current instant as a timezone-aware UTC datetime.

    Replacement for the deprecated ``datetime.utcnow()`` (which returned
    a *naive* UTC datetime — a footgun that silently re-localised when
    compared with aware datetimes).
    """
    return datetime.now(UTC)


def now_ny() -> datetime:
    """Current instant in US Eastern (America/New_York).

    Use for trading-day logic — DST handling matches what the NYSE
    publishes (no manual ``+ timedelta(hours=-4 or -5)`` arithmetic).
    """
    return datetime.now(NY)


def today_str_ny() -> str:
    """Today's date in NY zone as ``YYYY-MM-DD``.

    Daily snapshots, EOD report keys, "today's quote" filtering — all
    of those use this so a 23:30 UTC tick on the East Coast (which is
    still "today" in NY trading terms) lands under the right date.
    """
    return now_ny().strftime("%Y-%m-%d")


def utc_iso_z() -> str:
    """Return ``now_utc()`` formatted as the ISO 8601 ``...Z`` string
    every JSON contract in this codebase serialises to."""
    return now_utc().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
