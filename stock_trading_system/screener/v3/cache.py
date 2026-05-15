"""(ticker, guru, date) cache for GuruSignal results.

Uses the existing LocalCache with category 'guru_signal_v3'.
TTL = end of trading day (auto-expire on new day).
"""

from __future__ import annotations

from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_ny

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.cache")

CACHE_CATEGORY = "guru_signal_v3"


def _cache_key(ticker: str, guru: str, date: str) -> str:
    return f"{ticker}:{guru}:{date}"


def _seconds_until_end_of_day() -> int:
    # P2.5 step-2: guru signals are valid through the NY trading day;
    # base the EOD cutoff on Eastern time so a 23:30 UTC tick (which
    # is still afternoon in NY) doesn't pre-expire the cache.
    now = now_ny()
    end = now.replace(hour=23, minute=59, second=59)
    return max(60, int((end - now).total_seconds()))


def get_cached(
    local_cache, ticker: str, guru: str, date: str,
) -> GuruSignal | None:
    """Read a cached GuruSignal, or None."""
    if local_cache is None:
        return None
    try:
        raw = local_cache.get(CACHE_CATEGORY, _cache_key(ticker, guru, date))
        if raw:
            return GuruSignal.model_validate_json(raw)
    except Exception as e:
        logger.debug("Cache read failed for %s/%s: %s", ticker, guru, e)
    return None


def set_cached(
    local_cache, ticker: str, guru: str, date: str, signal: GuruSignal,
) -> None:
    """Write a GuruSignal to cache with end-of-day TTL."""
    if local_cache is None:
        return
    try:
        local_cache.set(
            CACHE_CATEGORY,
            _cache_key(ticker, guru, date),
            signal.model_dump_json(),
            ttl=_seconds_until_end_of_day(),
        )
    except Exception as e:
        logger.debug("Cache write failed for %s/%s: %s", ticker, guru, e)
