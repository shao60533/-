"""Natural language query parser (Qwen).

Turns a user query like "AI 板块被低估的成长股" into a structured FilterSpec
that the universe filter and downstream agents can consume.

Graceful degradation:
  - Empty / missing query → FilterSpec with market hint only
  - Qwen unavailable → FilterSpec with raw query saved as fallback keyword
  - Qwen returns bad JSON → same as unavailable
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict

from stock_trading_system.utils import get_logger
from stock_trading_system.data.qwen_provider import QwenProvider

logger = get_logger("screener.v2.nl_parser")


_SYSTEM_PROMPT = """你是股票筛选助手。将用户的自然语言查询解析为严格的 JSON FilterSpec。

规则:
1. 输出必须是合法 JSON，无多余文字。
2. 字段缺失时使用 null（不要省略键）。
3. market 只能是 "us" 或 "cn"。
4. sectors 使用 GICS 行业英文名（如 Technology, Semiconductors, Healthcare, Financials, Consumer Discretionary, Industrials, Energy, Materials, Utilities, Real Estate, Communication Services, Consumer Staples）。
5. themes 是用户意图的主题标签（如 AI, Electric Vehicle, Cloud Computing, Cybersecurity, Biotech）。
6. 百分比字段都是数字（15 表示 15%，不要写 "15%"）。
7. target_count 是希望初筛出的候选数，默认 30，用户明确说多/少时调整。
8. intent_summary 用简短中文回显你对用户意图的理解（不超过 30 字）。

FilterSpec JSON 规范:
{
  "intent_summary": "string",
  "market": "us" | "cn",
  "sectors": [string, ...] | null,
  "themes": [string, ...] | null,
  "criteria": {
    "min_market_cap": number | null,   // USD
    "max_market_cap": number | null,
    "max_pe": number | null,
    "min_pe": number | null,
    "max_pb": number | null,
    "min_roe_pct": number | null,       // percent, e.g. 15 = 15%
    "min_revenue_growth_pct": number | null,
    "min_dividend_yield_pct": number | null,
    "max_beta": number | null,
    "min_price": number | null,
    "max_price": number | null,
    "recent_signal": string | null      // e.g. "new_high_volume" | "positive_earnings_revision" | "buyback" | "oversold_bounce"
  },
  "exclude_tickers": [string, ...] | null,
  "target_count": number,
  "natural_fallback": [string, ...]    // 当解析不确定时，把原意图拆为 2-3 条关键字用于降级搜索
}"""


@dataclass
class FilterSpec:
    """Parsed natural-language query → structured filter."""
    intent_summary: str = ""
    market: str = "us"
    sectors: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    criteria: dict = field(default_factory=dict)
    exclude_tickers: list[str] = field(default_factory=list)
    target_count: int = 30
    natural_fallback: list[str] = field(default_factory=list)
    raw_query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_qwen_dict(cls, d: dict, raw_query: str) -> "FilterSpec":
        """Build from Qwen's raw JSON (with defensive key lookups)."""
        d = d or {}
        crit = d.get("criteria") or {}
        return cls(
            intent_summary=(d.get("intent_summary") or "").strip(),
            market=(d.get("market") or "us").lower(),
            sectors=list(d.get("sectors") or []),
            themes=list(d.get("themes") or []),
            criteria={
                "min_market_cap": crit.get("min_market_cap"),
                "max_market_cap": crit.get("max_market_cap"),
                "max_pe": crit.get("max_pe"),
                "min_pe": crit.get("min_pe"),
                "max_pb": crit.get("max_pb"),
                "min_roe_pct": crit.get("min_roe_pct"),
                "min_revenue_growth_pct": crit.get("min_revenue_growth_pct"),
                "min_dividend_yield_pct": crit.get("min_dividend_yield_pct"),
                "max_beta": crit.get("max_beta"),
                "min_price": crit.get("min_price"),
                "max_price": crit.get("max_price"),
                "recent_signal": crit.get("recent_signal"),
            },
            exclude_tickers=list(d.get("exclude_tickers") or []),
            target_count=int(d.get("target_count") or 30),
            natural_fallback=list(d.get("natural_fallback") or []),
            raw_query=raw_query,
        )


class NLParser:
    """Parse NL query → FilterSpec. Cached per (query, market) hash."""

    def __init__(self, config: dict, local_cache=None):
        self._config = config
        self._qwen = QwenProvider(config)
        self._cache = local_cache

    def parse(
        self,
        query: str | None,
        market_hint: str | None = None,
        strategy_hint: str | None = None,
    ) -> FilterSpec:
        """Parse a user query into a FilterSpec.

        If `query` is empty, returns a minimal spec using the market hint.
        Strategy hint (from the legacy chip) is appended as a soft preference
        in the natural_fallback list.
        """
        q = (query or "").strip()
        market = (market_hint or "us").lower()

        # Empty NL → legacy behavior (default universe, strategy hint only)
        if not q:
            fb = []
            if strategy_hint:
                fb.append(strategy_hint)
            return FilterSpec(
                intent_summary="(未提供 NL 查询，按 market 默认筛选)",
                market=market,
                target_count=30,
                natural_fallback=fb,
                raw_query="",
            )

        # Cache lookup (TTL handled by LocalCache)
        cache_key = hashlib.md5(f"{q}|{market}|{strategy_hint or ''}".encode()).hexdigest()
        if self._cache is not None:
            cached = self._cache.get("nl_parse", cache_key)
            if cached:
                try:
                    return FilterSpec(**cached)
                except Exception:
                    pass

        # Qwen call with hard timeout (NL parse should be fast, <10s)
        if not self._qwen.enabled:
            logger.info("Qwen disabled; NL parse falls back to raw query keyword")
            return self._fallback_spec(q, market, strategy_hint)

        user_prompt = self._build_user_prompt(q, market, strategy_hint)
        raw = self._call_with_timeout(user_prompt, timeout=15.0)

        if not raw:
            return self._fallback_spec(q, market, strategy_hint)

        spec = FilterSpec.from_qwen_dict(raw, raw_query=q)

        # Market hint wins if Qwen didn't specify
        if not spec.market:
            spec.market = market

        # Cache result
        if self._cache is not None:
            try:
                self._cache.set("nl_parse", cache_key, spec.to_dict())
            except Exception:
                pass

        logger.info(
            "NL parsed: intent='%s' sectors=%s themes=%s count=%d",
            spec.intent_summary[:50], spec.sectors, spec.themes, spec.target_count,
        )
        return spec

    def _call_with_timeout(self, user_prompt: str, timeout: float = 15.0) -> dict | None:
        """Call Qwen with a hard wall-clock timeout (using a worker thread)."""
        import threading
        result_box: dict = {"result": None, "error": None}

        def _worker():
            try:
                result_box["result"] = self._qwen._call(_SYSTEM_PROMPT, user_prompt)  # noqa: SLF001
            except Exception as e:  # noqa: BLE001
                result_box["error"] = str(e)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("NL parse Qwen call exceeded %.1fs, falling back", timeout)
            return None
        if result_box["error"]:
            logger.warning("NL parse Qwen call failed: %s", result_box["error"])
            return None
        return result_box["result"]

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _build_user_prompt(query: str, market: str, strategy_hint: str | None) -> str:
        parts = [f"用户查询: {query}", f"市场偏好: {market}"]
        if strategy_hint:
            parts.append(f"用户勾选的策略标签（弱提示，可参考也可忽略）: {strategy_hint}")
        parts.append("请输出 FilterSpec JSON。")
        return "\n".join(parts)

    @staticmethod
    def _fallback_spec(query: str, market: str, strategy_hint: str | None) -> FilterSpec:
        """Build a best-effort FilterSpec when Qwen is unavailable."""
        fb = [query]
        if strategy_hint:
            fb.append(strategy_hint)
        return FilterSpec(
            intent_summary=f"(Qwen 不可用，按关键词降级搜索) {query[:30]}",
            market=market,
            target_count=30,
            natural_fallback=fb,
            raw_query=query,
        )
