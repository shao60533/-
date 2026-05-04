"""Theme-aware fallback universes for V2/V3 screening.

When a user runs a strongly themed query like "存储龙头股" or "电力股
龙头" the LLM may return nothing (timeout, JSON error, provider down)
or, worse, return the curated mega-cap polluters BRK-B / JPM / V / MA
/ UNH / WMT / PG. The legacy code fell back to ``_DEFAULT_US`` — a
broad-market list — which leaked those names into themed results.

This module is the **single source of truth** for theme detection,
on-theme fallback universes, off-theme blacklist filtering, and
prompt-help metadata. Both ``UniverseFilter`` (Layer A/B) and
``ScreenerV3Pipeline`` (candidate-level theme_fit gate) read from
here so the two layers stay in lock-step without an extra plumbing
hop, and adding a new theme means updating ``_THEMES`` once.

v1.3 (2026-05-04) additions:
* ``Theme.sectors`` — GICS sector tags so the candidate-level theme_fit
  gate can match by sector when the ticker isn't in the curated
  fallback (e.g. an LLM-found utility we hadn't named).
* ``Theme.disambiguation_note`` — short Chinese hint surfaced in the
  NLParser prompt + ``_fallback_spec`` so the LLM and the no-LLM path
  share the same theme semantics ("电力股 = Utilities, not generic
  energy"; "新能源 = EV+光伏+风电+储能").
* ``Theme.is_strong`` — when True, ``UniverseFilter`` must
  fail-closed: never return ``_DEFAULT_US``, always run
  ``filter_off_theme`` over LLM output, and accept a short on-theme
  list rather than padding with broad-market polluters.
* New themes: ``power_utilities`` / ``traditional_energy`` /
  ``clean_energy`` / ``grid_electrification``.
* Public helper ``theme_metadata(theme_key)`` returns a dict the LLM
  prompt builder + the front-end run-metadata banner both consume.
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
    sectors: tuple[str, ...] = ()
    disambiguation_note: str = ""
    is_strong: bool = True
    extra_when_explicit: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Optional list of (keyword, extra-tickers) pairs. The extras only
    join the fallback universe when one of the listed keywords appears
    verbatim in the query — used by the storage theme to add cloud
    names only when the user wrote 云存储/对象存储/S3 etc."""


_BROAD_MARKET_BLACKLIST: frozenset[str] = frozenset({
    # Mega-cap broad-market polluters that the legacy _DEFAULT_US bled
    # into themed queries. Conservative — only obvious non-tech /
    # non-thematic anchors. v1.3: also covers power/energy themes that
    # mustn't pull in financial/consumer-staple anchors. XOM/CVX kept
    # because they ARE on-theme for the traditional_energy registry —
    # blacklist filtering checks per-theme membership, not just this
    # set, via ``filter_off_theme``.
    "BRK-B", "BRK.B", "BRKB",
    "JPM", "BAC", "WFC",
    "V", "MA",
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT",
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "HD",
    "DIS",
})

# Per-theme extra exclusions: tickers the registry-defined fallback
# wouldn't include but legacy ``_DEFAULT_US`` does. Indexed by theme
# key — drop tech mega-caps from a power query, drop oil & gas from a
# clean-energy query, etc.
_THEME_SPECIFIC_BLACKLIST: dict[str, frozenset[str]] = {
    "memory_storage": frozenset({
        "AAPL", "META", "TSLA", "NFLX", "CRM", "ADBE", "CSCO", "ACN",
        "IBM",
    }),
    "power_utilities": frozenset({
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA",
        "NFLX", "AVGO", "AMD", "CRM",
        "XOM", "CVX", "COP", "EOG",
    }),
    "traditional_energy": frozenset({
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA",
        "NFLX", "AVGO", "AMD", "CRM",
        "NEE", "DUK", "SO", "AEP",
        "FSLR", "ENPH", "SEDG", "BEP",
    }),
    "clean_energy": frozenset({
        "XOM", "CVX", "COP", "EOG", "MPC", "PSX", "SLB",
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NFLX", "AVGO",
        "AMD", "CRM",
    }),
    "grid_electrification": frozenset({
        "XOM", "CVX", "COP", "EOG",
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NFLX",
    }),
}


_THEMES: tuple[Theme, ...] = (
    # ── Memory & storage hardware ──────────────────────────────────
    Theme(
        key="memory_storage",
        keywords=(
            "存储", "存儲",
            "内存", "記憶體",
            "闪存", "閃存", "DRAM", "NAND",
            "SSD", "HDD", "硬盘", "硬碟",
            "数据存储", "数据中心存储",
            "memory chip", "memory semiconductor", "data storage",
            "storage", "memory",
            "S3", "Azure Storage", "Google Cloud Storage",
        ),
        universe=(
            "MU", "WDC", "STX", "SNDK",
            "MRVL", "AVGO", "INTC", "AMD", "NVDA",
        ),
        sectors=("Semiconductors", "Technology Hardware"),
        disambiguation_note=(
            "「存储」默认指 DRAM/NAND/闪存/SSD/HDD/数据存储硬件 / "
            "半导体存储产业链。仅当用户明确写 云存储 / 对象存储 / "
            "S3 / Azure Storage / Google Cloud Storage 时，才把 "
            "AMZN/MSFT/GOOGL 视为主题成员。"
        ),
        extra_when_explicit=(
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
    # ── Power utilities ────────────────────────────────────────────
    Theme(
        key="power_utilities",
        keywords=(
            "电力", "電力", "电力股", "電力股",
            "公用事业", "公用事業",
            "发电", "發電", "电网供电", "電網供電",
            "utility", "utilities", "power generation",
            "electric utility", "electric utilities",
        ),
        universe=(
            "NEE", "SO", "DUK", "AEP", "EXC",
            "SRE", "PEG", "ED", "XEL", "D",
        ),
        sectors=("Utilities",),
        disambiguation_note=(
            "「电力股 / 电力 / 公用事业」默认指美股 Utilities sector "
            "下的发电+电力公用事业，不是泛能源（油气）也不是科技。"
            "首选 NEE / SO / DUK / AEP / EXC / SRE / PEG / ED / "
            "XEL / D。"
        ),
    ),
    # ── Traditional oil & gas energy ───────────────────────────────
    Theme(
        key="traditional_energy",
        keywords=(
            "能源股", "能源",
            "石油", "天然气", "天然氣", "油气", "油氣",
            "炼油", "煉油",
            "oil", "gas", "petroleum", "refinery", "refiner",
            "exploration & production", "upstream",
        ),
        universe=(
            "XOM", "CVX", "COP", "EOG",
            "SLB", "LNG", "MPC", "PSX",
        ),
        sectors=("Energy",),
        disambiguation_note=(
            "「能源股 / 能源」默认指美股 Energy sector 下的油气链 "
            "（上游勘探+下游炼化+服务），不是 Utilities，更不是科技。"
            "如果用户明确写「清洁能源」/「新能源」/「可再生」/"
            "「光伏」/「风电」/「储能」，应改用 clean_energy 主题。"
        ),
    ),
    # ── Clean / renewable energy ───────────────────────────────────
    Theme(
        key="clean_energy",
        keywords=(
            "新能源", "清洁能源", "清潔能源",
            "可再生能源", "可再生",
            "光伏", "太阳能", "太陽能",
            "风电", "風電", "风能", "風能",
            "储能", "儲能", "电池储能", "電池儲能",
            "renewable", "renewables", "solar", "wind",
            "battery storage", "energy storage",
            "clean energy", "clean tech",
        ),
        universe=(
            "NEE", "FSLR", "ENPH", "SEDG",
            "BEP", "CWEN", "ARRY", "FLNC",
        ),
        sectors=(
            "Renewable Energy", "Solar", "Wind",
            "Energy Storage", "Utilities",
        ),
        disambiguation_note=(
            "「新能源 / 清洁能源」默认拆解为 EV + 光伏 + 风电 + 储能 "
            "+ 可再生能源公用事业。**禁止混入** AAPL/BRK-B/V/JPM "
            "等泛大盘股或纯油气股。首选 NEE/FSLR/ENPH/SEDG/BEP/"
            "CWEN/ARRY/FLNC。"
        ),
    ),
    # ── Grid / electrification ─────────────────────────────────────
    Theme(
        key="grid_electrification",
        keywords=(
            "电网", "電網", "输配电", "輸配電",
            "电气化", "電氣化", "电力设备", "電力設備",
            "grid", "transmission", "electrification",
            "power equipment", "power infrastructure",
        ),
        universe=(
            "ETN", "PWR", "GE", "GEV",
            "HUBB", "APTV", "ABBNY",
        ),
        sectors=(
            "Industrials", "Electrical Equipment",
            "Construction & Engineering",
        ),
        disambiguation_note=(
            "「电网 / 输配电 / 电气化 / 电力设备」对应 Industrials "
            "下的电气设备 + 工程承包公司，不是 Utilities 自己运营的"
            "电网。首选 ETN/PWR/GE/GEV/HUBB/APTV/ABBNY。"
        ),
    ),
)


# ── Public API ──────────────────────────────────────────────────────────


def detect_theme(
    query: str | None,
    intent_summary: str | None = None,
    themes: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
) -> Theme | None:
    """Return the matched Theme or ``None`` for off-theme queries.

    Matching is case-insensitive substring across all four signals:
    user query, parsed intent_summary, parsed themes list, parsed
    sectors list. Detection priority puts ``clean_energy`` BEFORE
    ``traditional_energy`` so "新能源" routes to renewables not oil &
    gas, and ``power_utilities`` BEFORE ``traditional_energy`` so
    "电力股" routes to utilities not generic "能源".
    """
    haystack_parts: list[str] = []
    if query:
        haystack_parts.append(query)
    if intent_summary:
        haystack_parts.append(intent_summary)
    if themes:
        haystack_parts.extend(str(t) for t in themes if t)
    if sectors:
        haystack_parts.extend(str(s) for s in sectors if s)
    if not haystack_parts:
        return None
    haystack = " ".join(haystack_parts).lower()

    # Priority must put clean_energy / power_utilities /
    # grid_electrification BEFORE memory_storage, otherwise
    # memory_storage's bare "storage" keyword false-positives on the
    # "Energy Storage" sector tag that the clean_energy fallback
    # template injects (the regression: "新能源龙头" routed to
    # memory_storage and pulled MU/WDC instead of NEE/FSLR). Energy
    # bucket goes last so "能源股" only matches traditional_energy
    # after the more specific clean / power / grid checks.
    priority_order = (
        "clean_energy",
        "power_utilities",
        "grid_electrification",
        "memory_storage",
        "traditional_energy",
    )
    by_key = {t.key: t for t in _THEMES}
    for key in priority_order:
        theme = by_key.get(key)
        if theme is None:
            continue
        for kw in theme.keywords:
            if kw.lower() in haystack:
                return theme
    return None


def is_strong_theme(theme: Theme | None) -> bool:
    """Whether the caller must fail-closed (no ``_DEFAULT_US`` fallback,
    LLM output must run through ``filter_off_theme``)."""
    return bool(theme and theme.is_strong)


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
    """Drop broad-market and theme-specific polluters from an
    LLM-returned ticker list when we are inside a theme.

    Off-theme queries are left untouched — generic "大盘蓝筹" or
    "美股龙头" remains free to pull from the broad universe.

    Two layers of filtering:
        1. ``_BROAD_MARKET_BLACKLIST`` (mega-cap anchors that pollute
           every theme).
        2. ``_THEME_SPECIFIC_BLACKLIST[theme.key]`` (per-theme extras
           — e.g. drop oil-&-gas names from a clean-energy result).

    On-theme curated fallback always passes (XOM is on-theme for
    traditional_energy even though it's heavyweight, and NEE is
    on-theme for both clean_energy and power_utilities).
    ``extra_when_explicit`` allow-list always wins both filters so
    AMZN/MSFT/GOOGL survive when the user explicitly asked for cloud
    storage even though they're on the broad blacklist for plain
    storage queries.
    """
    if theme is None:
        return [t.upper() for t in tickers if t]

    explicit_extras: set[str] = set()
    if query and theme.extra_when_explicit:
        q = query
        for trigger, extras in theme.extra_when_explicit:
            if trigger.lower() in q.lower() or trigger in q:
                explicit_extras.update(extras)

    on_theme_universe = set(theme.universe)
    theme_blacklist = _THEME_SPECIFIC_BLACKLIST.get(theme.key, frozenset())

    out: list[str] = []
    for raw in tickers:
        if not raw:
            continue
        t = str(raw).upper().strip()
        if t in explicit_extras:
            out.append(t)
            continue
        if t in on_theme_universe:
            out.append(t)
            continue
        if t in _BROAD_MARKET_BLACKLIST:
            continue
        if t in theme_blacklist:
            continue
        out.append(t)
    return out


def broad_market_blacklist() -> frozenset[str]:
    """Exposed for tests + callers that want to inspect the contract."""
    return _BROAD_MARKET_BLACKLIST


def theme_metadata(theme_key: str) -> dict | None:
    """Return a JSON-friendly snapshot of the theme registry for
    consumers (NLParser prompt builder + front-end banner). Returns
    ``None`` for unknown keys.
    """
    for theme in _THEMES:
        if theme.key == theme_key:
            return {
                "key":                  theme.key,
                "keywords":             list(theme.keywords),
                "universe":             list(theme.universe),
                "sectors":              list(theme.sectors),
                "disambiguation_note":  theme.disambiguation_note,
                "is_strong":            theme.is_strong,
                "extra_when_explicit":  [
                    {"trigger": trig, "extras": list(extras)}
                    for trig, extras in theme.extra_when_explicit
                ],
            }
    return None


def all_theme_keys() -> list[str]:
    """Stable list of registered theme keys, in detection-priority
    order (matches ``detect_theme``'s scan)."""
    return [
        "clean_energy",
        "power_utilities",
        "grid_electrification",
        "memory_storage",
        "traditional_energy",
    ]


def all_theme_metadata() -> list[dict]:
    """Convenience: ``theme_metadata`` for every registered theme,
    in priority order. Used by NLParser prompt builder."""
    return [m for m in (theme_metadata(k) for k in all_theme_keys()) if m]
