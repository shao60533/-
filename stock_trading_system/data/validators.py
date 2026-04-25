"""Sanity checks for LLM-sourced market data.

LLM responses occasionally include numbers that are out of any plausible
range (hallucinations). These validators drop clearly bogus values so
that callers never show garbage to the user. Uncertain values are kept
— the UI is responsible for labelling the source ("by Qwen · 仅供参考").
"""

from __future__ import annotations

from typing import Iterable


# Per-field plausibility bounds. (min, max) inclusive. None = no bound.
# Percentage fields are expressed as percentages (25.3 means 25.3%).
_FUNDAMENTALS_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "market_cap": (0, 1e14),          # up to $100T
    "pe_ratio": (-1000, 10000),       # allow negative (loss-making)
    "pb_ratio": (0, 10000),
    "roe": (-500, 500),               # percent
    "gross_margin": (-100, 100),
    "net_margin": (-500, 500),
    "revenue_growth": (-100, 10000),
    "dividend_yield": (0, 100),
    "beta": (-10, 10),
    "week_52_high": (0, 1e7),
    "week_52_low": (0, 1e7),
    "eps": (-10000, 10000),
}

# Fields that must be present (non-null) for the record to be useful.
# Empty list today means "any record with a ticker is acceptable" — we rely
# on bound filtering rather than all-or-nothing. Extend if stricter filtering
# is desired.
_FUNDAMENTALS_REQUIRED: list[str] = []


def validate_fundamentals(data: dict | None) -> dict | None:
    """Filter out-of-range numeric fields; drop record if too empty.

    Rules:
      - Missing ticker → None (useless record)
      - Each numeric field out of bounds → set to None
      - If after validation fewer than 3 fields have real values → None
    """
    if not data or not isinstance(data, dict):
        return None
    ticker = (data.get("ticker") or "").upper().strip()
    if not ticker:
        return None

    cleaned = dict(data)
    cleaned["ticker"] = ticker

    invalid_keys: list[str] = []
    for field, (lo, hi) in _FUNDAMENTALS_BOUNDS.items():
        v = cleaned.get(field)
        if v is None:
            continue
        if not isinstance(v, (int, float)):
            invalid_keys.append(field)
            cleaned[field] = None
            continue
        if lo is not None and v < lo:
            invalid_keys.append(field)
            cleaned[field] = None
        elif hi is not None and v > hi:
            invalid_keys.append(field)
            cleaned[field] = None

    # All required fields must still be present.
    if _FUNDAMENTALS_REQUIRED and any(
        cleaned.get(f) is None for f in _FUNDAMENTALS_REQUIRED
    ):
        return None

    # At least 3 numeric fields must be non-null to consider the record
    # informative. Otherwise the LLM likely hallucinated or knows nothing.
    non_null = sum(
        1 for f in _FUNDAMENTALS_BOUNDS
        if cleaned.get(f) is not None and isinstance(cleaned.get(f), (int, float))
    )
    if non_null < 3:
        return None

    if invalid_keys:
        cleaned["validation_warnings"] = invalid_keys
    return cleaned


def validate_news(items: Iterable[dict] | None) -> list[dict]:
    """Drop items with no http(s) URL or no title.

    The QwenProvider already filters these, but routing through the
    validator keeps a single source of truth for future fallbacks
    (yfinance news occasionally returns partial records too).
    """
    if not items:
        return []
    cleaned: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if not title:
            continue
        cleaned.append({
            "title": title,
            "url": url,
            "date": (item.get("date") or "").strip(),
            "source": (item.get("source") or "").strip(),
            "summary": (item.get("summary") or "").strip(),
        })
    return cleaned


def validate_quote(data: dict | None) -> dict | None:
    """Ensure a quote has a usable price. Reject garbage prices."""
    if not data or not isinstance(data, dict):
        return None
    last = data.get("last") if "last" in data else data.get("close")
    try:
        last_f = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_f = None
    if last_f is None or last_f <= 0 or last_f > 1e7:
        return None
    return data
