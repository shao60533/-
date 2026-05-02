"""Base guru agent interface and GuruSignal Pydantic schema.

All 14 guru agents extend BaseGuruAgent and return GuruSignal via
LangChain's chat.with_structured_output(GuruSignal).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.guru_agents")


# ── Theme instruction injected into every guru's system prompt ───────────
#
# Every guru's `_llm_reason` call prepends this block to its philosophical
# system prompt. The block is anchored to the user's verbatim query and
# the parsed FilterSpec so the LLM cannot silently drift to "AAPL is a
# wonderful business" when the user asked for storage names.
#
# A `theme_fit` SubAnalysis (0-10) becomes a hard requirement — the
# post-processor `_enforce_theme_fit` reads it back and caps total_score
# / signal when the LLM tries to give a high score to an off-theme pick.
# Off-theme queries (intent_summary / themes / sectors / natural_fallback
# all empty) still get the instruction so the LLM at least includes a
# theme_fit slot, but the cap is permissive (any score passes).

def _build_roundtable_theme_clause(nl_query: str | None) -> str:
    """Tiny helper used by ``roundtable._build_debate_prompt``.

    When the user's original NL query carries a strong theme keyword
    (storage / memory / cloud-storage), the debate prompt forces each
    speaker to explicitly answer "is this ticker even on-theme?" before
    arguing the financial bull/bear thesis. Off-theme queries (empty or
    no theme keyword) get an empty string so the speaker prompt stays
    short.

    Match logic mirrors the lightweight detection used by
    ``screener.v2.universe`` so debate gating and universe gating stay
    in lock-step. Cloud-storage check runs before bare-storage check
    because "云存储" is also a substring of "存储".
    """
    if not nl_query:
        return ""
    q = nl_query.lower()
    cloud_kw = ("云存储", "云计算", "对象存储", "云服务",
                "cloud storage", "object storage", "cloud computing")
    storage_kw = ("存储", "内存", "闪存", "nand", "dram",
                  "ssd", "硬盘", "hdd", "数据存储", "memory",
                  "flash storage", "data storage hardware")
    if any(k in q for k in cloud_kw):
        return (
            "用户主题：云存储 / 对象存储。请先回答："
            "该 ticker 是否对云存储 / S3 / Azure Storage / Google Cloud "
            "Storage 等云存储业务有直接收入暴露？无则视为不符合主题。\n"
        )
    if any(k in q for k in storage_kw):
        return (
            "用户主题：半导体存储 / 内存 / SSD / HDD 产业链。请先回答："
            "该 ticker 是否在 DRAM / NAND / 存储芯片 / 存储硬件 业务上有"
            "直接收入暴露？无则视为不符合主题，应给出 neutral/bearish。\n"
        )
    return ""


def _build_theme_instruction(query: str | None, spec: dict | None) -> str:
    """Return the universal theme/spec-aware preamble.

    Always non-empty so every guru evaluation produces a `theme_fit`
    slot — that gives `_enforce_theme_fit` something to read regardless
    of whether we detected a theme. Empty inputs degrade gracefully:
    the LLM sees ``"用户原始筛选意图: "`` and ``"结构化筛选条件: {}"``
    and the cap-rules become no-ops because theme_fit defaults to 5.

    v1.4 — Theme-fit content lives in ``sub_analyses[name="theme_fit"]``
    ONLY. The earlier version told the LLM to lead ``reasoning`` with
    a theme-mismatch paragraph, which made every guru's first 120
    characters say the same thing for off-theme tickers (the
    "大师评分详情同质化" bug). The lead is now reserved for the
    per-guru framework conclusion (see ``_build_reasoning_format_instruction``).
    """
    q = query or ""
    s = spec if isinstance(spec, dict) else {}
    return f"""

用户原始筛选意图: {q}
结构化筛选条件: {s}

重要约束：
1. 你不是在做泛股票分析，而是在判断该股票是否满足用户的筛选意图。
2. 如果用户查询包含行业/主题词，必须先评估 ticker 与该主题的直接业务相关性。
3. "龙头股"表示用户指定主题/行业内的龙头，不是全市场市值龙头。
4. 如果 ticker 与用户主题明显无关，即使财务指标优秀，也应降低 total_score，
   并将 signal 设为 neutral 或 bearish。
5. 主题匹配性的说明放在 sub_analyses 的 theme_fit 项里，不要写在 reasoning 开头。
   reasoning 第一句必须是你自己投资框架的结论（详见下面的"reasoning 结构要求"）。
6. 必须在 sub_analyses 中包含一项:
   {{"name": "theme_fit", "score": 0-10, "details": "该公司与用户主题的直接相关性说明"}}
7. 如果 theme_fit < 4，total_score 不应超过 60。
8. 如果 theme_fit < 2，signal 必须是 neutral 或 bearish。
9. 不能因为公司财务稳健，就在主题明显不匹配时给 bullish。
10. 如果用户查询包含"存储/内存/DRAM/NAND/SSD/HDD/闪存/数据存储硬件"，
    默认指半导体存储或存储硬件产业链。
    直接相关公司示例：MU, WDC, STX, SNDK。
    可作为产业链相关但需说明理由的公司：MRVL, INTC, AMD, NVDA, AVGO。
    无直接相关性的公司示例：BRK-B, JPM, V, MA, PG, WMT, UNH。
    除非用户明确写"云存储/云计算/对象存储"，否则 AMZN/MSFT/GOOGL 不应被默认视为存储龙头。
"""


def _build_data_coverage_caveat(bundle: dict | None) -> str:
    """Inspect the GuruDataBundle and emit a SystemMessage caveat
    listing missing data buckets, so the LLM can't pretend it has
    enough context when news / history / price-history are empty.

    Triggered when:
        * ``news_recent`` is missing or empty
        * ``fundamentals_history`` is empty AND there's no
          ``price_history_summary`` (or the summary has no return %)
        * ``sector_industry`` lacks both sector and industry

    Returns ``""`` when coverage is healthy so we don't pad the prompt
    needlessly. Returns a short Chinese block when one or more buckets
    are missing — the rule is "数据不足时不得仅凭快照下高分", which we
    pin verbatim so reviewers can grep for it.
    """
    if not isinstance(bundle, dict):
        return ""

    missing: list[str] = []
    news = bundle.get("news_recent")
    if not (isinstance(news, list) and len(news) > 0):
        missing.append("最近新闻")

    fund_hist = bundle.get("fundamentals_history") or []
    price_hist = bundle.get("price_history_summary") or {}
    has_price_summary = bool(
        isinstance(price_hist, dict)
        and any(price_hist.get(k) is not None for k in (
            "return_1m_pct", "return_3m_pct", "return_6m_pct",
            "sma200_distance_pct",
        ))
    )
    if not fund_hist and not has_price_summary:
        missing.append("历史基本面 + 价格走势")
    elif not fund_hist:
        missing.append("历史基本面")
    elif not has_price_summary:
        missing.append("价格走势")

    sector_industry = bundle.get("sector_industry") or {}
    if not (sector_industry.get("sector") or sector_industry.get("industry")):
        missing.append("行业分类")

    if not missing:
        return ""

    return (
        "\n\n数据覆盖度提醒：当前数据包缺少 ["
        + " / ".join(missing)
        + "]。**历史/新闻数据不足，不得仅凭快照下高分** — "
        + "请将这一限制写入 sub_analyses 中名为 data_coverage 的条目，"
        + "并在 reasoning 第三段（风险）显式提及该限制。"
        + "若依据明显不足以支撑 bullish/bearish 结论，"
        + "请把 signal 设为 neutral 并下调 confidence。"
    )


def _build_reasoning_format_instruction(framework_lead: str) -> str:
    """Force the LLM to structure ``reasoning`` so each guru sounds like
    themselves and not a templated theme-fit statement.

    The shape was driven by the v1.4 "大师评分详情同质化" report — every
    guru's first 120 characters was the same theme-mismatch sentence
    because both the system prompt and the theme instruction told them
    to lead with theme content. We now reserve the lead for the guru's
    own framework conclusion (Buffett → moat/cash-flow/margin-of-safety,
    Lynch → growth-stage/PEG/retail-friendly, Graham → valuation/balance-
    sheet/safety, Munger → quality/competitive-advantage/complexity, etc.)
    and push theme content into sub_analyses.

    ``framework_lead`` is the per-guru hint pulled off
    ``BaseGuruAgent.framework_lead``. It's a short Chinese phrase that
    names the dimensions the LLM must conclude on first.
    """
    lead = framework_lead.strip() or "你的核心投资框架"
    return f"""

reasoning 结构要求（必须严格遵守）：
1. reasoning 第一句必须以你的投资框架结论开头 —— {lead}。
   不能用"该公司主题匹配 …"、"该 ticker 与用户主题 …"作开头。
2. reasoning 整体按下面 3 段组织（用句号或换行分隔即可，不要用编号）：
   段一(必须，1-2 句): 你的框架结论（基于 {lead}）。
   段二(必须，1-3 句): 1-2 条核心依据，引用具体子分析或数字。
   段三(必须，1-2 句): 主要风险或反方观点（最弱子分析、估值担忧、主题契合度等）。
3. 主题契合度的描述只放进 sub_analyses[name=theme_fit]，不要放进 reasoning 段一。
4. 不要在 reasoning 中重复 sub_analyses 的所有打分；挑最关键的 2-3 项就够了。
5. reasoning 全文 240-480 字；过短会被认为没说理，过长会被截断。
"""


def _enforce_theme_fit(signal: "GuruSignal", context: dict | None) -> "GuruSignal":
    """Post-process a GuruSignal so a low ``theme_fit`` sub-analysis caps
    total_score and forces signal to neutral/bearish.

    Pydantic v2 `BaseModel` is mutable by default — we still use
    ``model_copy(update=...)`` to make the contract explicit and
    re-validate. Off-theme queries (empty nl_query) get a no-op since
    `theme_fit` will default to 5 and the rules are permissive there.
    """
    fit_score: float | None = None
    for sa in signal.sub_analyses or []:
        if (sa.name or "").strip().lower() == "theme_fit":
            fit_score = float(sa.score)
            break
    if fit_score is None:
        return signal

    new_total = signal.total_score
    new_signal = signal.signal

    # < 2: hard block on bullish AND drop the score floor more aggressively.
    if fit_score < 2:
        new_total = min(new_total, 45.0)
        if new_signal == "bullish":
            new_signal = "bearish"
    elif fit_score < 4:
        new_total = min(new_total, 60.0)
        if new_signal == "bullish":
            new_signal = "neutral"

    if new_total == signal.total_score and new_signal == signal.signal:
        return signal
    return signal.model_copy(update={
        "total_score": new_total,
        "signal": new_signal,
    })


class SubAnalysis(BaseModel):
    """One dimension of a guru's evaluation (e.g. moat, valuation)."""
    name: str
    score: float = Field(ge=0, le=10)
    details: str


class GuruSignal(BaseModel):
    """Structured output from a guru agent's deep evaluation."""
    guru: str
    ticker: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    sub_analyses: list[SubAnalysis]
    key_metrics: dict[str, float] = Field(default_factory=dict)
    total_score: float = Field(ge=0, le=100)


# Explicit JSON example for LLMs that need format guidance (Qwen, etc.)
_GURU_SIGNAL_EXAMPLE = """{
  "guru": "buffett",
  "ticker": "AAPL",
  "signal": "bullish",
  "confidence": 0.85,
  "reasoning": "Strong moat and consistent earnings growth...",
  "sub_analyses": [
    {"name": "fundamental_quality", "score": 8.5, "details": "ROE 25% excellent"},
    {"name": "economic_moat", "score": 7.0, "details": "Brand + ecosystem"}
  ],
  "key_metrics": {"intrinsic_value": 220.0, "margin_of_safety": 0.18},
  "total_score": 82.5
}"""


def _coerce_to_guru_signal(raw: dict, guru_name: str, ticker: str) -> GuruSignal:
    """Tolerant parsing of LLM output that doesn't perfectly match schema.

    Handles common Qwen/Gemini format issues:
    - sub_analyses as dict instead of list
    - key_metrics with string values instead of float
    - signal value outside the enum (e.g. "avoid" → "bearish")
    - missing fields with sensible defaults
    """
    # Fix signal enum
    sig = str(raw.get("signal", "neutral")).lower().strip()
    signal_map = {
        "buy": "bullish", "strong_buy": "bullish", "positive": "bullish",
        "sell": "bearish", "strong_sell": "bearish", "negative": "bearish",
        "avoid": "bearish", "short": "bearish",
        "hold": "neutral", "wait": "neutral",
    }
    if sig not in ("bullish", "bearish", "neutral"):
        sig = signal_map.get(sig, "neutral")

    # Fix confidence
    conf = raw.get("confidence", 0.5)
    try:
        conf = float(conf)
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.5

    # Fix sub_analyses: dict → list
    sa_raw = raw.get("sub_analyses", [])
    sub_analyses = []
    if isinstance(sa_raw, dict):
        for k, v in sa_raw.items():
            if isinstance(v, dict):
                sub_analyses.append(SubAnalysis(
                    name=k, score=min(10, max(0, float(v.get("score", 5)))),
                    details=str(v.get("details", "")),
                ))
            else:
                try:
                    score = float(v)
                except (TypeError, ValueError):
                    score = 5.0
                sub_analyses.append(SubAnalysis(name=k, score=min(10, max(0, score)), details=""))
    elif isinstance(sa_raw, list):
        for item in sa_raw:
            if isinstance(item, dict):
                try:
                    sub_analyses.append(SubAnalysis(**item))
                except Exception:
                    sub_analyses.append(SubAnalysis(
                        name=str(item.get("name", "unknown")),
                        score=min(10, max(0, float(item.get("score", 5)))),
                        details=str(item.get("details", "")),
                    ))

    # Fix key_metrics: filter non-numeric values
    km_raw = raw.get("key_metrics", {})
    key_metrics = {}
    if isinstance(km_raw, dict):
        for k, v in km_raw.items():
            try:
                key_metrics[k] = float(v)
            except (TypeError, ValueError):
                pass  # skip non-numeric entries

    # Fix total_score
    ts = raw.get("total_score", 50)
    try:
        ts = max(0, min(100, float(ts)))
    except (TypeError, ValueError):
        ts = 50.0

    return GuruSignal(
        guru=raw.get("guru", guru_name),
        ticker=raw.get("ticker", ticker),
        signal=sig,
        confidence=conf,
        reasoning=str(raw.get("reasoning", "")),
        sub_analyses=sub_analyses,
        key_metrics=key_metrics,
        total_score=ts,
    )


class BaseGuruAgent:
    """Abstract base for all guru agents."""
    name: str = ""
    display_name: str = ""
    philosophy: str = ""
    principles: list[str] = []
    motto: str = ""
    avatar_initials: str = ""
    avatar_color: str = "#888"
    # v1.4 — short Chinese phrase naming the dimensions this guru must
    # conclude on first inside ``reasoning``. Drives
    # ``_build_reasoning_format_instruction`` so every guru's leading
    # sentence sounds like itself and not a templated theme-fit
    # statement. Subclasses MUST override; falling back to ``philosophy``
    # is OK for the 10 less-named gurus (philosophy is already distinct
    # per guru) but the four leads called out in the spec
    # (buffett/lynch/graham/munger) override explicitly so the lead
    # phrasing matches the user's expectations.
    framework_lead: str = ""

    def evaluate_deep(
        self, ticker: str, full_data: dict, context: dict,
    ) -> GuruSignal:
        raise NotImplementedError

    def _get_chat_model(self, context: dict):
        """Get a LangChain chat model for the active provider."""
        provider = context.get("provider", "qwen")
        config = context.get("config", {})

        if provider == "qwen":
            from langchain_openai import ChatOpenAI
            qwen_cfg = config.get("qwen", {})
            return ChatOpenAI(
                model=qwen_cfg.get("model", "qwen-plus"),
                api_key=qwen_cfg.get("api_key", ""),
                base_url=qwen_cfg.get("base_url",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                timeout=120,
            )
        else:
            from langchain_google_genai import ChatGoogleGenerativeAI
            gemini_cfg = config.get("gemini", {})
            return ChatGoogleGenerativeAI(
                model=gemini_cfg.get("model", "gemini-2.5-flash"),
                google_api_key=gemini_cfg.get("api_key", ""),
                timeout=120,
            )

    def _llm_reason(
        self,
        system_prompt: str,
        user_prompt: str,
        ticker: str,
        context: dict,
    ) -> GuruSignal:
        """Common LLM reasoning with tolerant parsing.

        Strategy:
        1. Try with_structured_output(GuruSignal) first (LangChain native)
        2. On validation error, fall back to raw JSON + _coerce_to_guru_signal
        3. On total failure, return neutral fallback
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        import json

        chat = self._get_chat_model(context)

        # Theme instruction: rendered with the user's verbatim query and
        # the parsed FilterSpec dict so the LLM sees the user's actual
        # subject (not a paraphrase) plus the structured fields. Always
        # non-empty — off-theme runs simply get default-permissive caps
        # via `_enforce_theme_fit` because theme_fit defaults to 5.
        theme_instruction = _build_theme_instruction(
            query=(context or {}).get("nl_query"),
            spec=(context or {}).get("filter_spec"),
        )

        # screener-v3 v1.4: data-coverage caveat. When the bundle is
        # missing recent news, fundamentals history, or price history,
        # tell the model up-front so it can't conclude "基本面强劲"
        # purely from a single quote snapshot. Bundle is threaded into
        # context by concurrency._invoke; absent for legacy callers.
        coverage_caveat = _build_data_coverage_caveat(
            (context or {}).get("__bundle__"),
        )

        # v1.4 — per-guru reasoning-format instruction. Forces the
        # leading sentence of ``reasoning`` to be the framework
        # conclusion (e.g. Buffett's moat/cash-flow/margin-of-safety)
        # so the four cards in the UI read distinctly per guru. Falls
        # back to ``self.philosophy`` for any guru that hasn't set its
        # own ``framework_lead`` explicitly — every guru already has a
        # distinct philosophy string.
        reasoning_format = _build_reasoning_format_instruction(
            self.framework_lead or self.philosophy or "你的核心投资框架",
        )

        # Build messages with explicit schema example
        schema_instruction = (
            f"\n\nYou MUST respond with a valid JSON object matching this exact schema. "
            f"signal MUST be exactly one of: \"bullish\", \"bearish\", \"neutral\". "
            f"sub_analyses MUST be a JSON array (not an object). "
            f"key_metrics values MUST be numbers (not strings like \"N/A\"). "
            f"Use 0.0 for unknown numeric values.\n\n"
            f"Example output:\n{_GURU_SIGNAL_EXAMPLE}"
        )

        messages = [
            SystemMessage(content=(
                system_prompt
                + theme_instruction
                + coverage_caveat
                + reasoning_format
                + schema_instruction
            )),
            HumanMessage(content=user_prompt),
        ]

        # Attempt 1: LangChain structured output
        try:
            structured = chat.with_structured_output(GuruSignal)
            signal = structured.invoke(messages)
            return _enforce_theme_fit(signal, context)
        except Exception as e:
            logger.debug("structured_output failed for %s/%s: %s", self.name, ticker, e)

        # Attempt 2: Raw chat → tolerant parse
        try:
            raw_resp = chat.invoke(messages)
            content = raw_resp.content if hasattr(raw_resp, 'content') else str(raw_resp)

            # Extract JSON from response (may have markdown fences)
            json_str = content
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]

            raw_dict = json.loads(json_str.strip())
            signal = _coerce_to_guru_signal(raw_dict, self.name, ticker)
            logger.info("Tolerant parse succeeded for %s/%s: %s %.0f%%",
                        self.name, ticker, signal.signal, signal.confidence * 100)
            return _enforce_theme_fit(signal, context)
        except Exception as e2:
            logger.warning("Both structured and tolerant parse failed for %s/%s: %s",
                           self.name, ticker, e2)
            # Return neutral fallback
            return GuruSignal(
                guru=self.name, ticker=ticker, signal="neutral",
                confidence=0.0, reasoning=f"LLM parsing failed: {e2}",
                sub_analyses=[], key_metrics={}, total_score=0,
            )

    def to_meta(self) -> dict:
        """Return guru metadata for the frontend."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "philosophy": self.philosophy,
            "principles": self.principles,
            "motto": self.motto,
            "avatar_initials": self.avatar_initials,
            "avatar_color": self.avatar_color,
        }
