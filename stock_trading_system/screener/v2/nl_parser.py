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

logger = get_logger("screener.v2.nl_parser")


_SYSTEM_PROMPT = """你是股票筛选助手。将用户的自然语言查询解析为严格的 JSON FilterSpec。

规则:
1. 输出必须是合法 JSON，无多余文字。
2. 字段缺失时使用 null（不要省略键）。
3. market 只能是 "us" 或 "cn"。
4. sectors 使用 GICS 行业英文名（如 Technology, Semiconductors, Healthcare, Financials, Consumer Discretionary, Industrials, Energy, Materials, Utilities, Real Estate, Communication Services, Consumer Staples）。
5. themes 是用户意图的主题标签（如 AI, Electric Vehicle, Cloud Computing, Cybersecurity, Biotech, Memory, DRAM, NAND, Flash Storage, SSD, HDD, Data Storage Hardware, Semiconductor Storage）。
6. 百分比字段都是数字（15 表示 15%，不要写 "15%"）。
7. target_count 是希望初筛出的候选数，默认 30，用户明确说多/少时调整。
8. intent_summary 用简短中文回显你对用户意图的理解（不超过 30 字）。
9. 中文行业词需要按股票语境消歧：
   - "存储" 默认表示存储芯片 / 内存 / DRAM / NAND / 闪存 / SSD / HDD / 数据存储硬件 / 半导体存储产业链。对应 themes 应包含 "Memory Semiconductors" 与 "Data Storage Hardware"，sectors 应为 "Semiconductors" 或 "Technology Hardware"。
   - 不要把 "存储龙头股" 泛化为大盘蓝筹、价值股、金融股、消费股或普通科技巨头（禁止把 BRK-B / JPM / V / MA / UNH / WMT / PG 写进 natural_fallback 或建议排除）。
   - 只有用户明确写 "云存储" / "云计算存储" / "对象存储" / "云服务存储" / "S3" / "Azure Storage" / "Google Cloud Storage" 时，才把 AMZN / MSFT / GOOGL 等云平台股纳入主题；普通 "存储" 不算。
   - 类似的消歧也适用于 "芯片"（半导体）/ "新能源"（电动车 + 光伏 + 储能）/ "医药"（制药 + 生物科技）等中文模糊词，按主语境锁定主题。
10. "龙头股" / "龙头" / "龙一" / "龙二" 表示用户指定主题或行业内部的龙头，而不是全市场市值龙头。解析时：
    - 必须把主题信息写入 themes（用户主题不变，仅强调 "leader"），不要把主题清空让 sectors / criteria 自由发散。
    - 不要为了凑数把无关主题的大市值股写入 natural_fallback。
    - 如果用户没指定主题，"龙头股" 才解释为对应市场的大市值龙头。
11. 如果用户查询是强主题查询（如"存储"/"AI"/"新能源"/"半导体"），themes / natural_fallback 必须保留主题关键词；
    不能只输出 "Large Cap" / "Quality" / "Value" 这类泛标签，否则下游会把主题信息丢失。
12. 中文电力 / 能源 / 新能源主题消歧（v1.3 — 与 ``theme_universe.py`` 注册表对齐）：
    - "电力" / "电力股" / "公用事业" / "发电" 默认指 **Utilities sector** 的发电+电力公用事业（NEE/SO/DUK/AEP/EXC/SRE/PEG/ED/XEL/D），**不是泛能源、不是科技、也不是金融**；themes 应包含 "Utilities" / "Power Generation"，sectors 应为 "Utilities"。
    - "能源股" / "能源" 默认指 **Energy sector** 油气链（XOM/CVX/COP/EOG/SLB/LNG/MPC/PSX）；只有用户明确写「清洁能源」/「新能源」/「可再生」/「光伏」/「风电」/「储能」时才视为 clean_energy 主题。
    - "新能源" / "清洁能源" / "可再生能源" 默认拆解为 **EV + 光伏 + 风电 + 储能 + 可再生能源公用事业**（NEE/FSLR/ENPH/SEDG/BEP/CWEN/ARRY/FLNC）；themes 应包含 "Renewable Energy" / "Solar" / "Wind" / "Energy Storage"。**严禁混入** AAPL/BRK-B/V/JPM/META/MSFT/GOOGL 等泛大盘股或纯油气股（XOM/CVX/COP）。
    - "电网" / "输配电" / "电气化" / "电力设备" 对应 **Industrials 下电气设备 + 工程承包**（ETN/PWR/GE/GEV/HUBB/APTV/ABBNY），不是 Utilities。
    - "龙头股" 仍指主题/行业内部龙头，不是全市场市值龙头。

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
        self._llm = None  # lazy via _get_llm()
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

        # LLM call with hard timeout (NL parse should be fast, <10s)
        llm = self._get_llm()
        if llm is None:
            logger.info("LLM unavailable; NL parse falls back to raw query keyword")
            return self._fallback_spec(q, market, strategy_hint)

        user_prompt = self._build_user_prompt(q, market, strategy_hint)
        raw = self._call_with_timeout(llm, user_prompt, timeout=15.0)

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

    def _call_with_timeout(self, llm, user_prompt: str, timeout: float = 15.0) -> dict | None:
        """Call the active LLM with a hard wall-clock timeout."""
        import json as _json
        import threading

        result_box: dict = {"result": None, "error": None}

        def _worker():
            try:
                raw_text = llm.chat(
                    system=_SYSTEM_PROMPT,
                    user=user_prompt,
                    json_mode=True,
                    timeout=int(timeout),
                )
                result_box["result"] = _json.loads(raw_text) if raw_text else None
            except _json.JSONDecodeError as e:
                logger.warning("LLM returned invalid JSON: %s", e)
                result_box["result"] = None
            except Exception as e:  # noqa: BLE001
                result_box["error"] = str(e)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("NL parse LLM call exceeded %.1fs, falling back", timeout)
            return None
        if result_box["error"]:
            logger.warning("NL parse LLM call failed: %s", result_box["error"])
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

    # v1.3: ``_fallback_spec`` delegates theme detection to the
    # canonical ``theme_universe.detect_theme`` so the no-LLM path uses
    # exactly the same priority order (clean_energy before
    # traditional_energy, power_utilities before traditional_energy)
    # that ``UniverseFilter.filter_by_spec`` will use later. The
    # per-theme FilterSpec template lives below.

    _THEME_FALLBACK_TEMPLATES: dict[str, dict] = {
        "memory_storage": {
            "intent_label": "存储产业链龙头",
            "sectors": ["Technology", "Semiconductors"],
            "themes": [
                "Memory", "DRAM", "NAND", "Flash Storage",
                "SSD", "HDD", "Data Storage Hardware",
                "Semiconductor Storage",
            ],
            "extra_fallback": [
                "存储芯片", "内存", "DRAM", "NAND",
                "闪存", "SSD", "硬盘", "数据存储硬件",
            ],
        },
        # Cloud-storage carve-out lives in theme_universe via
        # ``extra_when_explicit`` — the FilterSpec doesn't need a
        # separate template; downstream ``UniverseFilter`` reads the
        # cloud trigger keywords from the registry.
        "power_utilities": {
            "intent_label": "电力 / 公用事业龙头",
            "sectors": ["Utilities"],
            "themes": ["Utilities", "Power Generation", "Electric Utility"],
            "extra_fallback": [
                "电力", "公用事业", "发电",
                "utility", "power generation",
            ],
        },
        "traditional_energy": {
            "intent_label": "油气能源龙头",
            "sectors": ["Energy"],
            "themes": [
                "Oil & Gas", "Petroleum", "Refinery",
                "Exploration & Production", "Upstream",
            ],
            "extra_fallback": [
                "石油", "天然气", "油气", "炼油",
                "oil", "gas", "petroleum",
            ],
        },
        "clean_energy": {
            "intent_label": "新能源 / 清洁能源龙头",
            "sectors": [
                "Renewable Energy", "Utilities",
                "Solar", "Wind", "Energy Storage",
            ],
            "themes": [
                "Renewable Energy", "Solar", "Wind",
                "Battery Storage", "Energy Storage",
                "Clean Energy", "Electric Vehicle",
            ],
            "extra_fallback": [
                "新能源", "清洁能源", "可再生能源",
                "光伏", "风电", "储能",
                "renewable", "solar", "wind", "battery storage",
            ],
        },
        "grid_electrification": {
            "intent_label": "电网 / 电气化设备龙头",
            "sectors": [
                "Industrials", "Electrical Equipment",
                "Construction & Engineering",
            ],
            "themes": [
                "Grid", "Transmission", "Electrification",
                "Power Equipment", "Power Infrastructure",
            ],
            "extra_fallback": [
                "电网", "输配电", "电气化", "电力设备",
                "grid", "transmission", "electrification",
            ],
        },
    }

    @classmethod
    def _fallback_spec(cls, query: str, market: str, strategy_hint: str | None) -> FilterSpec:
        """Build a best-effort FilterSpec when Qwen is unavailable.

        Theme-aware: routes through ``theme_universe.detect_theme`` so
        a "电力股龙头" / "新能源龙头" / "存储龙头股" / "能源股" query
        all gets the right sectors + themes + natural_fallback even
        when the LLM never ran. Empty queries keep the legacy minimal
        spec — we never invent a theme out of nothing.
        """
        from stock_trading_system.screener.v2.theme_universe import detect_theme

        fb = [query] if query else []
        if strategy_hint:
            fb.append(strategy_hint)

        if not query:
            return FilterSpec(
                intent_summary="(LLM 不可用，按关键词降级搜索)",
                market=market,
                target_count=30,
                natural_fallback=fb,
                raw_query=query,
            )

        theme = detect_theme(query)
        template = (
            cls._THEME_FALLBACK_TEMPLATES.get(theme.key)
            if theme is not None
            else None
        )
        if theme is not None and template is not None:
            return FilterSpec(
                intent_summary=(
                    f"(LLM 不可用) {template['intent_label']} — {query[:30]}"
                ),
                market=market,
                sectors=list(template["sectors"]),
                themes=list(template["themes"]),
                target_count=30,
                natural_fallback=fb + list(template["extra_fallback"]),
                raw_query=query,
            )

        # No theme detected — preserve legacy keyword-only fallback.
        return FilterSpec(
            intent_summary=f"(LLM 不可用，按关键词降级搜索) {query[:30]}",
            market=market,
            target_count=30,
            natural_fallback=fb,
            raw_query=query,
        )
