"""Universe filter — produces candidate tickers for agent scoring.

V1.1: Driven by FilterSpec (from NL parser). Three-layer fallback:
  A) Qwen universe query (NL + criteria → ticker list via screen_stocks)
  B) Heuristic narrow (default list filtered by FilterSpec.criteria)
  C) Default fallback (~40 large-cap US stocks)

The old V1 strategy-chip path is preserved only as the default when no
FilterSpec is provided.
"""

from __future__ import annotations

from stock_trading_system.utils import get_logger
from stock_trading_system.data.qwen_provider import QwenProvider
from stock_trading_system.screener.v2.nl_parser import FilterSpec

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


class UniverseFilter:
    """Build candidate ticker list from a FilterSpec (or market hint)."""

    def __init__(self, config: dict, data_helper=None):
        self._config = config
        self._qwen = QwenProvider(config)
        self._data = data_helper

    # ── V1.1 main entry ────────────────────────────────────────────────

    def filter_by_spec(self, spec: FilterSpec, max_universe: int = 40) -> tuple[list[str], str]:
        """Return (tickers, source_layer) for the given FilterSpec.

        source_layer ∈ {"qwen", "heuristic", "default"} for transparency.
        """
        market = (spec.market or "us").lower()
        target = min(max_universe, max(5, spec.target_count or 30))

        # Layer A — Qwen
        if self._qwen.enabled:
            tickers = self._qwen_universe(spec, target, market)
            if tickers:
                return tickers[:max_universe], "qwen"
            logger.info("Layer A (Qwen) yielded 0 tickers, falling to Layer B")

        # Layer B — Heuristic narrow over default list
        defaults = _DEFAULT_US if market == "us" else _DEFAULT_CN
        narrowed = self._heuristic_filter(defaults, spec)
        if narrowed:
            return narrowed[:max_universe], "heuristic"

        # Layer C — Raw default
        return list(defaults)[:max_universe], "default"

    # ── V1 legacy path (kept for backward compat) ──────────────────────

    def filter(self, params: dict) -> list[str]:
        """V1 legacy path: market + optional strategy, no NL parsing."""
        market = (params.get("market") or "us").lower()
        max_n = int(params.get("max_universe", 40))
        defaults = _DEFAULT_US if market == "us" else _DEFAULT_CN
        return defaults[:max_n]

    # ── Layer A: Qwen ─────────────────────────────────────────────────

    def _qwen_universe(self, spec: FilterSpec, target: int, market: str) -> list[str]:
        """Use Qwen web-search to materialize a universe matching the spec.

        Builds a natural-language criteria string from FilterSpec fields
        and calls QwenProvider.screen_stocks if available, else falls back
        to a direct Qwen call that returns {tickers: [...]}.
        """
        criteria_text = self._spec_to_nl_criteria(spec)
        logger.info("Qwen universe query: %s", criteria_text[:100])

        # Prefer the existing screen_stocks API if it exists
        if hasattr(self._qwen, "screen_stocks"):
            try:
                picks = self._qwen.screen_stocks(
                    criteria=criteria_text,
                    market=market,
                    count=target,
                )
                # screen_stocks returns list of dicts (ticker+meta) or tickers
                out = []
                for p in picks or []:
                    if isinstance(p, dict):
                        t = p.get("ticker") or p.get("symbol")
                        if t:
                            out.append(str(t).upper())
                    elif isinstance(p, str):
                        out.append(p.upper())
                return out
            except Exception as e:  # noqa: BLE001
                logger.warning("Qwen screen_stocks failed: %s", e)

        # Fallback: direct call returning {tickers: [...]}
        system = (
            "你是股票筛选助手。根据用户的中文筛选条件，返回一组股票代码列表。"
            f"市场: {market.upper()}。返回 JSON: {{\"tickers\": [\"AAPL\", ...]}}, 不含其他文字。"
            f"目标数量约 {target}。只返回真实存在、流动性好的股票代码。"
        )
        user = criteria_text
        try:
            data = self._qwen._call(system, user)  # noqa: SLF001
        except Exception as e:  # noqa: BLE001
            logger.warning("Qwen direct universe call failed: %s", e)
            return []
        if not data:
            return []
        raw = data.get("tickers") or data.get("stocks") or []
        return [str(t).upper() for t in raw if t]

    @staticmethod
    def _spec_to_nl_criteria(spec: FilterSpec) -> str:
        """Translate FilterSpec → a natural-language criteria string for Qwen."""
        parts = []
        if spec.intent_summary:
            parts.append(f"核心意图: {spec.intent_summary}")
        if spec.themes:
            parts.append("主题: " + ", ".join(spec.themes))
        if spec.sectors:
            parts.append("行业: " + ", ".join(spec.sectors))
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
        if spec.natural_fallback:
            parts.append("关键词提示: " + "; ".join(spec.natural_fallback))
        if not parts and spec.raw_query:
            parts.append(spec.raw_query)
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
