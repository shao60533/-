"""Universe filter — produces candidate tickers for agent scoring.

V1.1: Driven by FilterSpec (from NL parser). Three-layer fallback:
  A) Qwen universe query (NL + criteria → ticker list via screen_stocks)
  B) Heuristic narrow (default list filtered by FilterSpec.criteria)
  C) Default fallback (~40 large-cap US stocks)

The old V1 strategy-chip path is preserved only as the default when no
FilterSpec is provided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_trading_system.utils import get_logger

if TYPE_CHECKING:
    # FilterSpec only appears in type annotations — keep the runtime
    # dependency on ``nl_parser`` optional so a test that stubs the
    # nl_parser module (e.g. v3 pipeline fallback test) can still
    # import-and-use UniverseFilter via the constants exposed below.
    from stock_trading_system.screener.v2.nl_parser import FilterSpec  # noqa: F401

logger = get_logger("screener.v2.universe")


# Curated large-cap US default list (Layer C)
_DEFAULT_US = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "MA", "XOM", "UNH", "LLY", "JNJ", "WMT", "PG", "HD",
    "AVGO", "COST", "NFLX", "AMD", "CRM", "ADBE", "ORCL", "CSCO",
    "PEP", "KO", "MRK", "ABBV", "BAC", "TMO", "ABT", "ACN", "MCD",
    "DIS", "QCOM", "INTC", "IBM", "GE",
]

_DEFAULT_CN = [
    "600519", "601318", "000858", "600036", "000333", "601166",
    "600276", "000001", "600030", "601888", "600887", "002594",
]


# Theme keyword + fallback constants. Put primary cloud-storage check
# before bare-storage check because "云存储" contains "存储" and we don't
# want hyperscalers to leak into a memory query.

_STORAGE_KEYWORDS = {
    "存储", "内存", "闪存", "nand", "dram", "ssd", "硬盘", "hdd", "数据存储",
    "memory", "flash storage", "semiconductor storage", "data storage hardware",
}

_CLOUD_STORAGE_KEYWORDS = {
    "云存储", "云计算", "对象存储", "云服务",
    "cloud storage", "object storage", "cloud computing",
}

# Tickers that must NEVER appear in a storage-themed result — their
# business has no direct memory/SSD/HDD exposure. Matches the spec
# requirement: BRK-B/JPM/V/MA/PG/WMT/UNH dropped from storage screens.
_STORAGE_EXCLUDED_US = {
    "BRK-B", "BRK.B", "BRKB",
    "JPM", "V", "MA", "PG", "WMT", "UNH",
}

_THEME_FALLBACKS_US = {
    "storage_semiconductor": [
        "MU", "WDC", "STX", "SNDK", "MRVL", "INTC", "AMD", "NVDA", "AVGO",
    ],
    "cloud_storage": [
        "AMZN", "MSFT", "GOOGL", "ORCL", "IBM", "SNOW", "NET",
    ],
}


class UniverseFilter:
    """Build candidate ticker list from a FilterSpec (or market hint)."""

    def __init__(self, config: dict, data_helper=None):
        self._config = config
        self._llm = None  # lazy via _get_llm()
        self._qwen = None  # lazy for screen_stocks data API
        self._data = data_helper

    # ── V1.1 main entry ────────────────────────────────────────────────

    def filter_by_spec(self, spec: FilterSpec, max_universe: int = 40) -> tuple[list[str], str]:
        """Return (tickers, source_layer) for the given FilterSpec.

        source_layer ∈ {"llm", "theme_fallback", "heuristic", "default"}
        for transparency.

        Theme-aware fallback order (v1.23):
          1. LLM (Qwen / Gemini) — output is run through
             ``_clean_theme_tickers`` so BRK-B/JPM/V/MA/PG/WMT/UNH never
             survive a storage query even if the model hallucinated them.
          2. Theme fallback — curated on-topic list (MU/WDC/STX/...) when
             the spec text matches storage/cloud-storage keywords.
             Strong-theme queries DO NOT fall through to ``_DEFAULT_US``.
          3. Heuristic narrow over ``_DEFAULT_US`` — also passes through
             ``_clean_theme_tickers`` in case the spec is themed but the
             theme fallback returned empty (defensive).
          4. Raw default — only for off-theme generic queries.
        """
        market = (spec.market or "us").lower()
        target = min(max_universe, max(5, spec.target_count or 30))

        # Compute theme fallback once — the same list seeds both the
        # standalone Layer 2 and any Layer 3 narrowing.
        theme_fallback = self._theme_fallback_universe(spec, market)

        # Layer A — LLM (Qwen or Gemini). Always run cleaning, even when
        # the LLM succeeds, so a polluted answer never reaches scoring.
        llm = self._get_llm()
        if llm is not None:
            tickers = self._llm_universe(llm, spec, target, market)
            tickers = self._clean_theme_tickers(tickers, spec, market)
            if tickers:
                return tickers[:max_universe], "llm"
            logger.info("Layer A (LLM) yielded 0 tickers, falling to Layer B")

        # Layer B — Theme fallback. Strong-theme queries stop here even
        # if the curated list is short; we'd rather return 4 on-topic
        # tickers than 40 broad-market polluters.
        if theme_fallback:
            cleaned = self._clean_theme_tickers(theme_fallback, spec, market)
            if cleaned:
                logger.info(
                    "Layer B theme_fallback for %r → %d tickers",
                    spec.raw_query, len(cleaned),
                )
                return cleaned[:max_universe], "theme_fallback"

        # Layer C — Heuristic narrow over default list
        defaults = _DEFAULT_US if market == "us" else _DEFAULT_CN
        narrowed = self._heuristic_filter(defaults, spec)
        narrowed = self._clean_theme_tickers(narrowed, spec, market)
        if narrowed:
            return narrowed[:max_universe], "heuristic"

        # Layer D — Raw default (off-theme only)
        return list(defaults)[:max_universe], "default"

    # ── Theme helpers ─────────────────────────────────────────────────

    @staticmethod
    def _spec_text(spec: FilterSpec) -> str:
        """Concatenate every signal-bearing field of the spec into a
        single lower-case haystack for keyword matching. Includes
        raw_query / intent_summary / themes / sectors / natural_fallback
        so a partial NLParser output (LLM gave themes but no raw_query)
        still triggers theme detection."""
        return " ".join([
            spec.raw_query or "",
            spec.intent_summary or "",
            " ".join(spec.themes or []),
            " ".join(spec.sectors or []),
            " ".join(spec.natural_fallback or []),
        ]).lower()

    def _theme_fallback_universe(self, spec: FilterSpec, market: str) -> list[str]:
        """Return a curated on-theme ticker list when the spec text
        triggers a known theme. ``[]`` when off-theme."""
        if market != "us":
            return []
        text = self._spec_text(spec)
        if any(k in text for k in _CLOUD_STORAGE_KEYWORDS):
            return list(_THEME_FALLBACKS_US["cloud_storage"])
        if any(k in text for k in _STORAGE_KEYWORDS):
            return list(_THEME_FALLBACKS_US["storage_semiconductor"])
        return []

    def _is_storage_theme(self, spec: FilterSpec, market: str) -> bool:
        """True when the spec maps to bare-storage (NOT cloud-storage).
        Used to gate the BRK-B/JPM/V/... blacklist — cloud-storage
        queries legitimately allow hyperscalers."""
        if market != "us":
            return False
        text = self._spec_text(spec)
        if any(k in text for k in _CLOUD_STORAGE_KEYWORDS):
            return False
        return any(k in text for k in _STORAGE_KEYWORDS)

    def _clean_theme_tickers(
        self, tickers: list[str], spec: FilterSpec, market: str,
    ) -> list[str]:
        """Drop blacklisted tickers (storage theme only), uppercase, and
        de-duplicate while preserving order."""
        out: list[str] = []
        seen: set[str] = set()
        is_storage = self._is_storage_theme(spec, market)
        for t in tickers:
            tt = str(t or "").upper().strip()
            if not tt or tt in seen:
                continue
            if is_storage and tt in _STORAGE_EXCLUDED_US:
                continue
            seen.add(tt)
            out.append(tt)
        return out

    # ── V1 legacy path (kept for backward compat) ──────────────────────

    def filter(self, params: dict) -> list[str]:
        """V1 legacy path: market + optional strategy, no NL parsing."""
        market = (params.get("market") or "us").lower()
        max_n = int(params.get("max_universe", 40))
        defaults = _DEFAULT_US if market == "us" else _DEFAULT_CN
        return defaults[:max_n]

    # ── Lazy init ──────────────────────────────────────────────────────

    def _get_llm(self):
        """Lazy-init the LLM text client via the global provider router."""
        if self._llm is None:
            try:
                from stock_trading_system.llm.client import get_text_client
                self._llm = get_text_client(self._config)
            except Exception as e:
                logger.warning("Failed to initialize LLM client: %s", e)
                return None
        return self._llm

    def _get_qwen(self):
        """Lazy-init QwenProvider for screen_stocks data API (not text completion)."""
        if self._qwen is None:
            try:
                from stock_trading_system.data.qwen_provider import QwenProvider
                self._qwen = QwenProvider(self._config)
            except Exception:
                pass
        return self._qwen

    # ── Layer A: LLM ─────────────────────────────────────────────────

    def _llm_universe(
        self, llm, spec: FilterSpec, target: int, market: str,
    ) -> list[str]:
        """Use LLM to materialize a universe matching the spec.

        First tries QwenProvider.screen_stocks (data API, Qwen-only),
        then falls back to a generic LLM call returning {tickers: [...]}.
        """
        import json as _json

        criteria_text = self._spec_to_nl_criteria(spec)
        logger.info("LLM universe query: %s", criteria_text[:100])

        # Prefer QwenProvider.screen_stocks data API when available
        qwen = self._get_qwen()
        if qwen and hasattr(qwen, "screen_stocks") and qwen.enabled:
            try:
                picks = qwen.screen_stocks(
                    criteria=criteria_text,
                    market=market,
                    count=target,
                )
                out = []
                for p in picks or []:
                    if isinstance(p, dict):
                        t = p.get("ticker") or p.get("symbol")
                        if t:
                            out.append(str(t).upper())
                    elif isinstance(p, str):
                        out.append(p.upper())
                if out:
                    return out
            except Exception as e:  # noqa: BLE001
                logger.warning("QwenProvider.screen_stocks failed: %s", e)

        # Generic LLM fallback. The system prompt is the strict v1.23
        # version: hard-codes the storage/cloud-storage carve-out so
        # even when the model hasn't seen rule 9 (NL parser) it still
        # refuses to pad with BRK-B/JPM/V/MA/PG/WMT/UNH.
        system = (
            "你是股票候选池生成助手。根据用户筛选条件返回股票代码。"
            "必须严格匹配用户主题，不要用泛大盘龙头、知名公司或高市值公司凑数。"
            "如果用户查询包含行业/主题词，只能返回与该主题有直接业务暴露的公司。"
            "“龙头股”表示该主题/行业内部的龙头，不是全市场市值龙头。"
            "中文“存储”默认指存储芯片/内存/DRAM/NAND/闪存/SSD/HDD/数据存储硬件/半导体存储产业链；"
            "除非用户明确写云存储/云计算/对象存储/云服务，否则不要把 AMZN/MSFT/GOOGL 当作默认存储股。"
            "对存储主题，优先 MU/WDC/STX/SNDK；可补充有明确存储产业链暴露的 MRVL/INTC/AMD/NVDA/AVGO。"
            "禁止为存储主题返回 BRK-B/JPM/V/MA/PG/WMT/UNH 等无直接相关性的股票。"
            f"市场: {market.upper()}。返回 JSON: {{\"tickers\": [\"MU\", ...]}}，不含其他文字。"
            f"目标数量约 {target}；若直接相关股票不足，可以少于目标数量。"
        )
        try:
            raw_text = llm.chat(system=system, user=criteria_text, json_mode=True, timeout=30)
            data = _json.loads(raw_text) if raw_text else {}
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM universe call failed: %s", e)
            return []
        raw = data.get("tickers") or data.get("stocks") or []
        return [str(t).upper() for t in raw if t]

    @staticmethod
    def _spec_to_nl_criteria(spec: FilterSpec) -> str:
        """Translate FilterSpec → a natural-language criteria string for the LLM.

        v1.23 invariants:
          * raw_query is always included so the model sees the user's
            verbatim Chinese — keyword loss inside the structured fields
            no longer wipes out theme info.
          * themes / sectors / natural_fallback always echoed when
            present, even if intent_summary already mentions them.
        """
        parts = []
        if spec.raw_query:
            parts.append(f"用户原始查询: {spec.raw_query}")
        if spec.intent_summary:
            parts.append(f"核心意图: {spec.intent_summary}")
        if spec.themes:
            parts.append("主题: " + ", ".join(spec.themes))
        if spec.sectors:
            parts.append("行业: " + ", ".join(spec.sectors))
        if spec.natural_fallback:
            parts.append("关键词提示: " + "; ".join(spec.natural_fallback))
        c = spec.criteria or {}
        if c.get("min_market_cap"):
            parts.append(f"市值≥{int(c['min_market_cap']/1e9)}B USD")
        if c.get("max_pe"):
            parts.append(f"PE≤{c['max_pe']}")
        if c.get("min_pe"):
            parts.append(f"PE≥{c['min_pe']}")
        if c.get("max_pb"):
            parts.append(f"PB≤{c['max_pb']}")
        if c.get("min_roe_pct"):
            parts.append(f"ROE≥{c['min_roe_pct']}%")
        if c.get("min_revenue_growth_pct"):
            parts.append(f"收入增速≥{c['min_revenue_growth_pct']}%")
        if c.get("min_dividend_yield_pct"):
            parts.append(f"股息率≥{c['min_dividend_yield_pct']}%")
        if c.get("max_beta"):
            parts.append(f"Beta≤{c['max_beta']}")
        if c.get("recent_signal"):
            parts.append(f"近期信号: {c['recent_signal']}")
        if spec.exclude_tickers:
            parts.append("排除: " + ", ".join(spec.exclude_tickers))
        return "；".join(parts) or "大盘优质股票"

    # ── Layer B: Heuristic narrow ─────────────────────────────────────

    def _heuristic_filter(self, tickers: list[str], spec: FilterSpec) -> list[str]:
        """Filter a fixed universe by FilterSpec.criteria using DataHelper."""
        if not self._data:
            return list(tickers)
        c = spec.criteria or {}
        out = []
        for t in tickers:
            if spec.exclude_tickers and t in spec.exclude_tickers:
                continue
            f = self._data.get_fundamentals(t) or {}
            if not self._passes_criteria(f, c, spec.sectors):
                continue
            out.append(t)
        logger.info("Heuristic filter: %d → %d tickers", len(tickers), len(out))
        return out

    @staticmethod
    def _passes_criteria(f: dict, c: dict, sectors: list[str]) -> bool:
        """Boolean filter: True if fundamentals pass all criteria."""
        def _lt(v, cap):
            try:
                return v is not None and cap is not None and float(v) <= float(cap)
            except (ValueError, TypeError):
                return True
        def _gt(v, floor):
            try:
                return v is not None and floor is not None and float(v) >= float(floor)
            except (ValueError, TypeError):
                return True

        # Sector filter
        if sectors:
            sec = (f.get("sector") or "").lower()
            if not any(s.lower() in sec or sec in s.lower() for s in sectors):
                # Allow through if sector info missing (don't over-filter)
                if f.get("sector"):
                    return False

        if c.get("min_market_cap") and (f.get("market_cap") or 0) < c["min_market_cap"]:
            return False
        if c.get("max_market_cap") and f.get("market_cap") and f["market_cap"] > c["max_market_cap"]:
            return False

        pe = f.get("pe")
        if c.get("max_pe") and pe is not None and pe > 0 and pe > c["max_pe"]:
            return False
        if c.get("min_pe") and pe is not None and pe > 0 and pe < c["min_pe"]:
            return False

        if c.get("max_pb") and f.get("pb") and f["pb"] > c["max_pb"]:
            return False

        if c.get("min_roe_pct"):
            roe = f.get("roe")
            if roe is None or roe * 100 < c["min_roe_pct"]:
                return False

        if c.get("min_revenue_growth_pct"):
            rg = f.get("revenue_growth")
            if rg is None or rg * 100 < c["min_revenue_growth_pct"]:
                return False

        if c.get("max_beta"):
            b = f.get("beta")
            if b is not None and b > c["max_beta"]:
                return False

        return True
