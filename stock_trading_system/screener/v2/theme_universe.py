"""Theme-aware fallback universes for V2/V3 screening.

When a user runs a strongly themed query like "存储龙头股" the LLM may
return nothing (timeout, JSON error, provider down) and the legacy code
fell back to ``_DEFAULT_US`` — a curated mega-cap list that contains
BRK-B / JPM / V / MA / UNH / WMT / PG. None of those belong in a memory
or storage screening result, but they still showed up because the
fallback was theme-blind.

This module gives each known Chinese theme keyword:

* a curated **on-theme universe** — used when the LLM produces nothing
  AND the user query maps to the theme.
* an **off-theme blacklist** — applied to whatever the LLM returned, so
  even when Layer A succeeds the polluters never reach scoring.

Detection runs over the natural-language query, the parsed
``intent_summary`` and the parsed ``themes``. We do not add a new schema
field — themes drive both the prompt (rule 9 in nl_parser) and this
fallback, so the two layers stay in lock-step without an extra plumbing
hop.

Cloud-storage carve-out:普通 "存储" 不算云，只有显式写 "云存储" / "对象存储"
/ "S3" 等才把 AMZN/MSFT/GOOGL 视为主题内成员。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# ── Theme registry ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Theme:
    key: str
    keywords: tuple[str, ...]
    universe: tuple[str, ...]
    extra_when_explicit: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Optional list of (keyword, extra-tickers) pairs. The extras only
    join the fallback universe when one of the listed keywords appears
    verbatim in the query — used by the storage theme to add cloud names
    only when the user wrote 云存储/对象存储/S3 etc."""


_BROAD_MARKET_BLACKLIST: frozenset[str] = frozenset({
    # Mega-cap broad-market polluters that the legacy _DEFAULT_US bled
    # into themed queries. Keep this conservative — only obvious
    # non-tech / non-thematic anchors.
    "BRK-B", "BRK.B", "BRKB",
    "JPM", "BAC", "WFC",
    "V", "MA",
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT",
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "HD",
    "XOM", "CVX",
    "DIS",
    "GE",
})


# Curated on-theme tickers. Lists are intentionally short — the LLM is
# the primary source; this is the safety net.
_THEMES: tuple[Theme, ...] = (
    Theme(
        key="memory_storage",
        keywords=(
            # Storage / memory in Chinese.
            "存储", "存儲",
            "内存", "記憶體",
            "闪存", "閃存", "DRAM", "NAND",
            "SSD", "HDD", "硬盘", "硬碟",
            "数据存储", "数据中心存储",
            # English variants — "storage" alone is broad enough that we
            # also match "Azure Storage 龙头" without needing the user
            # to switch to Chinese.
            "memory chip", "memory semiconductor", "data storage",
            "storage", "memory",
            "S3", "Azure Storage", "Google Cloud Storage",
        ),
        # Pure-play memory + storage names. NVDA/AVGO/AMD/INTC are
        # adjacent semiconductor leaders the user explicitly listed as
        # acceptable extras for this theme.
        universe=(
            "MU", "WDC", "STX", "SNDK",
            "MRVL", "AVGO", "INTC", "AMD", "NVDA",
        ),
        extra_when_explicit=(
            # Only when the user explicitly says cloud storage do the
            # hyperscaler platforms count as on-theme.
            ("云存储", ("AMZN", "MSFT", "GOOGL")),
            ("云計算存儲", ("AMZN", "MSFT", "GOOGL")),
            ("云计算存储", ("AMZN", "MSFT", "GOOGL")),
            ("对象存储", ("AMZN", "MSFT", "GOOGL")),
            ("對象存儲", ("AMZN", "MSFT", "GOOGL")),
            ("云服务存储", ("AMZN", "MSFT", "GOOGL")),
            ("S3", ("AMZN",)),
            ("Azure Storage", ("MSFT",)),
            ("Google Cloud Storage", ("GOOGL",)),
        ),
    ),
)


# ── Public API ──────────────────────────────────────────────────────────

def detect_theme(
    query: str | None,
    intent_summary: str | None = None,
    themes: Iterable[str] | None = None,
) -> Theme | None:
    """Return the matched Theme or ``None`` for off-theme queries.

    Matching is case-insensitive substring across all three signals:
    user query, parsed intent_summary, parsed themes list. The first
    theme whose keywords match wins (registry is small, single-pass is
    fine).
    """
    haystack_parts: list[str] = []
    if query:
        haystack_parts.append(query)
    if intent_summary:
        haystack_parts.append(intent_summary)
    if themes:
        haystack_parts.extend(str(t) for t in themes if t)
    if not haystack_parts:
        return None
    haystack = " ".join(haystack_parts).lower()

    for theme in _THEMES:
        for kw in theme.keywords:
            if kw.lower() in haystack:
                return theme
    return None


def theme_fallback_universe(
    theme: Theme,
    *,
    query: str | None = None,
) -> list[str]:
    """Build the on-theme fallback ticker list, including the
    ``extra_when_explicit`` extras only when the user query contains
    one of the gating keywords (e.g. "云存储")."""
    out: list[str] = list(theme.universe)
    seen: set[str] = set(out)
    if query and theme.extra_when_explicit:
        q = query
        for trigger, extras in theme.extra_when_explicit:
            if trigger.lower() in q.lower() or trigger in q:
                for t in extras:
                    if t not in seen:
                        out.append(t)
                        seen.add(t)
    return out


def filter_off_theme(
    tickers: Iterable[str],
    theme: Theme | None,
    *,
    query: str | None = None,
) -> list[str]:
    """Drop broad-market polluters (BRK-B/JPM/V/MA/UNH/WMT/PG/...) from
    an LLM-returned ticker list when we are inside a theme.

    Off-theme queries are left untouched — generic "大盘蓝筹" or "美股
    龙头" remains free to pull from the broad universe.
    """
    if theme is None:
        return [t.upper() for t in tickers if t]

    explicit_extras: set[str] = set()
    if query and theme.extra_when_explicit:
        q = query
        for trigger, extras in theme.extra_when_explicit:
            if trigger.lower() in q.lower() or trigger in q:
                explicit_extras.update(extras)

    out: list[str] = []
    for raw in tickers:
        if not raw:
            continue
        t = str(raw).upper().strip()
        # An explicit extra (e.g. AMZN under "云存储") is always allowed
        # even when its ticker would otherwise hit the blacklist via a
        # non-thematic alias.
        if t in explicit_extras:
            out.append(t)
            continue
        if t in _BROAD_MARKET_BLACKLIST:
            continue
        out.append(t)
    return out


def broad_market_blacklist() -> frozenset[str]:
    """Exposed for tests + callers that want to inspect the contract."""
    return _BROAD_MARKET_BLACKLIST
