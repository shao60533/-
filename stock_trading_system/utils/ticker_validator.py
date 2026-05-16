"""Ticker normalization + market existence validation.

Centralizes the rule that every paper-trade entry point must pass through
before a ticker can reach the database. Prevents typo-driven duplicate
sessions (e.g. SXOL vs SOXL).

Validation has two layers:
  1. Form regex — US ``^[A-Z]{1,5}$`` / CN ``^\\d{6}(\\.(SH|SZ))?$`` (canonical
     drops the suffix and stores 6-digit code).
  2. Quote probe — call DataRouter.get_price(); if zero data sources have
     this code, treat the ticker as non-existent and reject.

A 5-minute in-process LRU keeps the hot path cheap: the same (ticker,
market) tuple validates once per process per 5min. ``allow_quote_failure``
opts out of layer 2 so degraded network does not block user submissions —
form-only validation still catches obvious typos.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from time import time
from typing import Callable, Optional


class InvalidTickerError(ValueError):
    """Raised when ticker cannot be normalized or fails quote probe."""

    def __init__(self, raw: object, reason: str) -> None:
        self.raw = raw
        self.reason = reason
        super().__init__(f"invalid ticker {raw!r}: {reason}")


@dataclass(frozen=True)
class TickerValidation:
    canonical: str
    market: str  # "us" | "cn"
    has_quote: bool
    quote_price: Optional[float]
    quote_date: Optional[str]


_US_RE = re.compile(r"^[A-Z]{1,5}$")
_CN_RE = re.compile(r"^(\d{6})(\.(SH|SZ))?$")

_CACHE_TTL = 300.0  # seconds
_CACHE: dict[tuple[str, str], tuple[float, TickerValidation]] = {}
_LOCK = threading.Lock()

QuoteFn = Callable[[str], Optional[dict]]


def _default_quote_fn(ticker: str) -> Optional[dict]:
    """Resolve a quote via the app's singleton DataRouter when present,
    falling back to a standalone instance for CLI / migration callers."""
    try:
        from stock_trading_system.web import app as _app_mod

        return _app_mod._get_data_router().get_price(ticker)  # type: ignore[attr-defined]
    except Exception:
        try:
            from stock_trading_system.data.data_router import DataRouter

            return DataRouter().get_price(ticker)
        except Exception:
            return None


def normalize_and_validate_ticker(
    raw: object,
    *,
    market_hint: Optional[str] = None,
    allow_quote_failure: bool = False,
    quote_fn: Optional[QuoteFn] = None,
) -> TickerValidation:
    """Normalize + validate. Raises InvalidTickerError on failure.

    Args:
        raw: User-supplied ticker string. None / non-str → reject.
        market_hint: Optional "us" | "cn" to disambiguate edge cases.
        allow_quote_failure: When True, a missing quote does NOT fail —
            returns has_quote=False so the caller can still proceed with
            form-only validation (used by code paths where blocking the
            user on a flaky data-source outage is worse than letting a
            rare bad ticker through). Form check still applies.
        quote_fn: Inject a callable for testing.
    """
    if raw is None or not isinstance(raw, str):
        raise InvalidTickerError(raw, "ticker is None or non-string")

    canonical_input = raw.strip().upper()
    if not canonical_input:
        raise InvalidTickerError(raw, "empty after trim")

    m_cn = _CN_RE.match(canonical_input)
    if m_cn:
        canonical = m_cn.group(1)
        market = "cn"
    elif _US_RE.match(canonical_input):
        canonical = canonical_input
        market = "us"
    else:
        raise InvalidTickerError(
            raw,
            "形态校验失败：不像 US (1-5 大写字母) 或 CN (6 位数字) 证券代码",
        )

    if market_hint in ("us", "cn"):
        market = market_hint

    key = (canonical, market)
    now = time()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL:
            return cached[1]

    fn = quote_fn or _default_quote_fn
    try:
        q = fn(canonical)
    except Exception:
        q = None

    price: Optional[float] = None
    quote_date: Optional[str] = None
    if isinstance(q, dict):
        raw_price = q.get("last") if q.get("last") is not None else q.get("close")
        try:
            price = float(raw_price) if raw_price is not None else None
        except (TypeError, ValueError):
            price = None
        quote_date = str(q.get("date") or q.get("timestamp") or "") or None

    if price is not None and price > 0:
        v = TickerValidation(
            canonical=canonical,
            market=market,
            has_quote=True,
            quote_price=price,
            quote_date=quote_date,
        )
    elif allow_quote_failure:
        v = TickerValidation(
            canonical=canonical,
            market=market,
            has_quote=False,
            quote_price=None,
            quote_date=None,
        )
    else:
        raise InvalidTickerError(raw, "市场未找到该代码（报价数据源 0 命中）")

    with _LOCK:
        _CACHE[key] = (now, v)
    return v


def _reset_cache_for_tests() -> None:
    """Test helper — wipes the in-process LRU."""
    with _LOCK:
        _CACHE.clear()
