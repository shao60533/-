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


# v1.3 (2026-05-04): Theme detection / on-theme fallback / off-theme
# blacklist all live in ``theme_universe.py`` now. The legacy module-
# level _STORAGE_KEYWORDS / _THEME_FALLBACKS_US / _CLOUD_STORAGE_KEYWORDS
# / _STORAGE_EXCLUDED_US tables that lived here have been deleted —
# adding a new theme used to require updating two places, which led to
# the "电力能源股 / 电力股龙头 / 能源股龙头 / 新能源龙头" regression
# where universe.py had no entry for them and silently fell back to
# ``_DEFAULT_US``. Single-source-of-truth removes that footgun.


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

        ``source_layer`` ∈ {"dynamic_llm", "theme_fallback",
        "heuristic", "default"} — clear semantics per v1.4:

        * ``dynamic_llm`` — Layer A succeeded. The LLM materialised a
          spec-driven candidate list (input-driven, NOT a registry
          lookup). Whether the count matched ``target`` is a separate
          concern surfaced via ``len(tickers)`` — the source label
          itself never lies about WHO produced the candidates.
        * ``theme_fallback`` — Layer A failed/empty. Curated registry
          list takes over so a themed query never silently degrades to
          mega-caps. UI shows a "primary candidate generation failed —
          using conservative fallback" warning when this fires.
        * ``heuristic`` — non-themed off-LLM path narrows the
          ``_DEFAULT_US`` list by spec criteria.
        * ``default`` — pure off-theme fallback for generic queries
          (e.g. "美股大盘"). Strong-theme queries are NOT allowed
          here (fail-closed).

        v1.4 dropped the ``partial_theme_fallback`` label that v1.3
        introduced — it conflated "Layer A LLM produced 8 of 10
        requested" with "Layer B fallback fired", which made the UI
        falsely warn "primary failed" for legitimate dynamic results.
        """
        from stock_trading_system.screener.v2 import theme_universe as tu

        market = (spec.market or "us").lower()
        target = min(max_universe, max(5, spec.target_count or 30))

        theme = self._detect_theme_for_spec(spec)
        is_strong = tu.is_strong_theme(theme)
        theme_fallback = (
            tu.theme_fallback_universe(theme, query=spec.raw_query)
            if (theme is not None and market == "us")
            else []
        )

        # Layer A — LLM (Qwen or Gemini). Always run cleaning, even
        # when the LLM succeeds, so a polluted answer never reaches
        # scoring. v1.4 — short LLM lists STAY ``dynamic_llm``: the
        # candidate-level theme_fit gate downstream still runs, so a
        # 6-ticker dynamic answer is materially different from a
        # 6-ticker registry lookup and the UI should reflect that.
        llm = self._get_llm()
        if llm is not None:
            tickers = self._llm_universe(llm, spec, target, market)
            tickers = self._clean_theme_tickers(
                tickers, theme=theme, query=spec.raw_query,
            )
            if tickers:
                return tickers[:max_universe], "dynamic_llm"
            logger.info("Layer A (LLM) yielded 0 tickers, falling to Layer B")

        # Layer B — Theme fallback. Conservative registry list, only
        # fires when LLM is unavailable or returned nothing usable.
        # The UI is expected to flag this with "primary candidate
        # generation failed" since it means we couldn't honour the
        # input-driven contract.
        if theme_fallback:
            cleaned = self._clean_theme_tickers(
                theme_fallback, theme=theme, query=spec.raw_query,
            )
            if cleaned:
                logger.info(
                    "Layer B theme_fallback for %r → %d tickers (theme=%s)",
                    spec.raw_query, len(cleaned),
                    theme.key if theme else "?",
                )
                return cleaned[:max_universe], "theme_fallback"

        # Layer C — Heuristic narrow over default list. Strong themes
        # may still recover here when DataHelper finds matching
        # sectors in the default list — but the result must STILL be
        # blacklist-cleaned, otherwise BRK-B can ride a "Financials"
        # sector match into a power-utility query.
        defaults = _DEFAULT_US if market == "us" else _DEFAULT_CN
        narrowed = self._heuristic_filter(defaults, spec)
        narrowed = self._clean_theme_tickers(
            narrowed, theme=theme, query=spec.raw_query,
        )
        if narrowed:
            return narrowed[:max_universe], "heuristic"

        # Layer D — Raw default. Strong themes are NOT allowed here
        # (fail-closed): we'd rather return the empty curated theme
        # universe than pollute a themed query with broad-market
        # mega-caps. If we ever reach this branch with a strong theme
        # both LLM AND the registry returned empty — should never
        # happen in practice; surface as ``theme_fallback`` so the
        # UI shows the source warning.
        if is_strong:
            logger.warning(
                "Strong theme %r produced empty universe across all layers",
                theme.key if theme else "?",
            )
            return list(theme_fallback)[:max_universe], "theme_fallback"
        return list(defaults)[:max_universe], "default"

    # ── Theme helpers ─────────────────────────────────────────────────

    @staticmethod
    def _spec_text(spec: FilterSpec) -> str:
        """Concatenate every signal-bearing field of the spec into a
        single lower-case haystack for keyword matching."""
        return " ".join([
            spec.raw_query or "",
            spec.intent_summary or "",
            " ".join(spec.themes or []),
            " ".join(spec.sectors or []),
            " ".join(spec.natural_fallback or []),
        ]).lower()

    def _detect_theme_for_spec(self, spec: FilterSpec):
        """v1.3: thin wrapper around ``theme_universe.detect_theme``
        so call sites consistently feed the same set of FilterSpec
        signals (raw_query + intent_summary + themes + sectors)."""
        from stock_trading_system.screener.v2 import theme_universe as tu
        return tu.detect_theme(
            query=spec.raw_query,
            intent_summary=spec.intent_summary,
            themes=spec.themes,
            sectors=spec.sectors,
        )

    @staticmethod
    def _clean_theme_tickers(
        tickers: list[str],
        *,
        theme=None,
        query: str | None = None,
    ) -> list[str]:
        """Uppercase + de-dup + run ``filter_off_theme`` (theme-aware
        broad-market blacklist + per-theme exclusions). Off-theme
        queries skip the blacklist — generic "美股大盘" still passes
        through unchanged."""
        from stock_trading_system.screener.v2 import theme_universe as tu

        # Normalise + dedupe in one pass.
        normalised: list[str] = []
        seen: set[str] = set()
        for t in tickers:
            tt = str(t or "").upper().strip()
            if not tt or tt in seen:
                continue
            seen.add(tt)
            normalised.append(tt)
        return tu.filter_off_theme(normalised, theme, query=query)

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

        # v1.3: switched from the misnamed ``screen_stocks(criteria=,
        # market=, count=)`` call (which always TypeError'd because
        # ``screen_stocks`` actually expects ``(candidates, strategy,
        # top_n)``) to ``materialize_universe(criteria, market,
        # count)`` — a dedicated NL→candidates entry point. Pre-v1.3
        # this whole branch silently failed every request and we fell
        # straight to the generic LLM fallback below.
        qwen = self._get_qwen()
        if qwen and hasattr(qwen, "materialize_universe") and qwen.enabled:
            try:
                # v1.4: prefer the FilterSpec-aware overload so the
                # prompt gets structured sector/theme/keyword fields
                # instead of a flattened criteria blob. Legacy
                # ``criteria=`` kwarg is still accepted as a positional
                # fallback for callers that don't have a spec.
                picks = qwen.materialize_universe(
                    spec=spec,
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
                logger.warning("QwenProvider.materialize_universe failed: %s", e)

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
