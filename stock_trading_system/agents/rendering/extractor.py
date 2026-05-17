"""Convert finished analyzer reports into per-tab Pydantic structured cards.

Six tabs (summary / Market / Sentiment / Investment Debate / Risk Assessment
/ Decision) are pure-LLM ``with_structured_output`` extractions over the
matching free-text report.

Two tabs use a hybrid strategy:

* **News** — real headlines come from ``data_manager.get_news()``; the LLM
  is asked to label sentiment + impact and add catalysts. Title / source
  / date are frozen by a hard guard: any LLM-emitted headline whose title
  doesn't match the real set is dropped, and any real headline the LLM
  forgot to tag is appended back so users never lose a real-world event.
* **Fundamentals** — numeric blocks (valuation / growth / profitability /
  balance_sheet) come from ``data_manager.get_fundamentals()``. The LLM
  may only contribute ``valuation.vs_industry`` (1 sentence),
  ``quality_score`` (1–5), and ``summary`` (1–3 sentences). After the LLM
  call we overwrite the numeric blocks with the real facts so a model
  that tries to "improve" PE silently is corrected.

Per-tab failure is isolated: one tab raising does not affect the others;
the failed key gets ``None`` and the frontend falls back to markdown.
The analyzer task is never blocked by an extraction failure.
"""

from __future__ import annotations

import json
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutTimeout,
    as_completed,
)
from typing import Any

from stock_trading_system.agents.rendering.data_sources import (
    fetch_fundamentals_facts,
    fetch_news_headlines,
)
from stock_trading_system.agents.rendering.schemas import (
    DebateCard,
    DecisionCard,
    FundamentalsCard,
    MarketCard,
    NewsCard,
    OverviewCard,
    RiskCard,
    SentimentCard,
)
from stock_trading_system.agents.rendering.state_normalizer import (
    normalize_state_to_text,
)
from stock_trading_system.utils import get_logger

logger = get_logger("agents.rendering.extractor")


# Language contract for every structured-output prompt below.
# Without this, the model echoes the analyst-report English (TradingAgents
# emits English even with output_language=Chinese for some sub-agents) and
# the user-facing card surfaces raw English plus enum keys like ``bear`` /
# ``SELL`` / ``high``. Schema enums (Literal) MUST stay English so the
# Pydantic validator accepts them; everything user-visible (claims,
# summaries, headlines, evidence …) MUST be Simplified Chinese.
_LANG_CLAUSE = (
    "所有面向用户展示的字段必须使用简体中文输出，包括 headline / detail / "
    "summary / claim / evidence / verdict / action_direction / "
    "one_line_summary / one_line_takeaway / neutral_synthesis / "
    "key_disagreement / vs_industry / mitigation 等。股票代码、公司英文名、"
    "指标缩写（PE / PB / ROE / RSI / MACD 等）可保留英文。"
    "schema 中的枚举字段（rating / confidence / trend / mood / signal / "
    "polarity / kind / sentiment / impact / verdict / final_action / "
    "conviction / time_horizon / weight / probability / severity / "
    "strength）必须用 schema 规定的英文枚举值（如 bullish / Buy / high），"
    "前端会做中文映射。禁止输出 JSON 字符串、Python dict repr 或模型内部键名。"
)


_SYS_GENERIC = (
    "You convert a stock-analysis report into a strict JSON schema. "
    "Use ONLY information present in the input — never invent prices, "
    "indicator values, dates, or news headlines. If a field is unknown, "
    "leave it null (or omit if optional). Verdict / synthesis fields are "
    "1–3 concise sentences; claim 1 sentence; evidence 1–2 sentences. "
    "Do NOT include personal-portfolio advice (sizing percentages tied to "
    "user holdings, personal entry timing). Technical objective price "
    "levels (SMA, support, resistance) are allowed.\n\n"
    + _LANG_CLAUSE
)

_SYS_NEWS = (
    "Enrich the provided REAL headlines: keep title/source/date AS-IS "
    "and only fill sentiment + impact based on the LLM context. "
    "Do NOT invent headlines. Add catalysts derived from the context. "
    "Write a 1-3 sentence summary.\n\n"
    + _LANG_CLAUSE
    + " 标题（title / source）保持原始语言不翻译，summary 与 catalysts.summary 用中文。"
)

_SYS_FUNDAMENTALS = (
    "Use the provided REAL facts AS-IS. Do NOT change pe / pb / ps / peg "
    "/ ev_ebitda / growth / profitability / balance_sheet numbers. "
    "Only write valuation.vs_industry (1 sentence comparing to sector), "
    "quality_score (1-5 integer), and summary (1-3 sentences).\n\n"
    + _LANG_CLAUSE
)


class RenderingExtractor:
    """Extract 8 structured cards. ``data_manager`` enables hybrid mode for
    News and Fundamentals; passing ``None`` falls back to pure-LLM extraction
    for those tabs (used by tests and offline replay)."""

    def __init__(self, llm: Any, data_manager: Any = None,
                 *, per_tab_timeout: float = 45.0):
        self._llm = llm
        self._dm = data_manager
        self._timeout = per_tab_timeout

    def extract(self, result, ticker: str = "") -> dict[str, dict | None]:
        # ``investment_debate`` / ``risk_assessment`` / ``trade_decision``
        # arrive as TradingAgents state dicts. ``str(d)`` would produce a
        # Python repr (``"{'judge_decision': '...'}"``) that the LLM has to
        # un-parse into prose; we normalise to Chinese-headed Markdown
        # instead so the prompt context, the structured-output input, and
        # the markdown fallback in the UI all use the same clean text.
        debate_text = normalize_state_to_text(
            getattr(result, "investment_debate", None),
            kind="investment_debate",
        )
        risk_text = normalize_state_to_text(
            getattr(result, "risk_assessment", None),
            kind="risk_debate",
        )
        decision_text = normalize_state_to_text(
            getattr(result, "trade_decision", None),
            kind="trade_decision",
        )

        tasks: list[tuple[str, Any, tuple]] = [
            ("summary",            self._extract_overview,     (result,)),
            ("Market",             self._extract_generic,
                ("Market", MarketCard, getattr(result, "market_report", "") or "")),
            ("Sentiment",          self._extract_generic,
                ("Sentiment", SentimentCard, getattr(result, "sentiment_report", "") or "")),
            ("News",               self._extract_news,         (result, ticker)),
            ("Fundamentals",       self._extract_fundamentals, (result, ticker)),
            ("Investment Debate",  self._extract_generic,
                ("Investment Debate", DebateCard, debate_text)),
            ("Risk Assessment",    self._extract_generic,
                ("Risk Assessment", RiskCard, risk_text)),
            ("Decision",           self._extract_generic,
                ("Decision", DecisionCard, decision_text)),
        ]
        out: dict[str, dict | None] = {}
        with ThreadPoolExecutor(max_workers=8,
                                 thread_name_prefix="render-extract") as pool:
            futs = {pool.submit(fn, *args): key
                    for (key, fn, args) in tasks}
            for fut in as_completed(futs):
                key = futs[fut]
                try:
                    out[key] = fut.result(timeout=self._timeout)
                except FutTimeout:
                    logger.warning("rendering extract %s timed out", key)
                    out[key] = None
                except Exception as e:  # noqa: BLE001
                    logger.warning("rendering extract %s failed: %s", key, e)
                    out[key] = None
        return out

    # ── Generic + Overview (pure LLM) ────────────────────────────────

    def _extract_generic(self, key: str, schema, content: str):
        if not content or not content.strip():
            return None
        structured = self._llm.with_structured_output(schema)
        obj = structured.invoke([
            {"role": "system", "content": _SYS_GENERIC},
            {"role": "user",   "content": f"[REPORT — {key}]\n{content}"},
        ])
        if obj is None:
            return None
        return obj.model_dump(exclude_none=False, mode="json")

    def _extract_overview(self, result):
        """Overview tab extraction with deterministic fallback.

        Pipeline:
          1. Try the LLM ``with_structured_output(OverviewCard)`` path
             (legacy v1.19 behaviour).
          2. If the LLM raises, returns ``None``, or its output fails
             Pydantic validation, do NOT return ``None`` — build a
             deterministic ``OverviewCard``-shaped dict from analyzer
             fields (``signal`` / ``trade_decision`` / source reports).
             The 概览 tab always gets *something* as long as ANY source
             report survived the analysis pipeline.

        Marker keys stamped on the returned dict:
          * ``_fallback_used`` — ``True`` when the deterministic path
            ran. ``_rendering_outputs`` promotes this to
            ``_meta.summary_source = 'fallback'``.
          * ``_fallback_error`` — short LLM error string for operator
            triage; never shown to the end user verbatim.

        Returns ``None`` only when EVERY source field is empty — i.e.
        a genuine ``empty`` row, not a structured-extraction failure.
        """
        debate_text = normalize_state_to_text(
            getattr(result, "investment_debate", None),
            kind="investment_debate",
        )
        risk_text = normalize_state_to_text(
            getattr(result, "risk_assessment", None),
            kind="risk_debate",
        )
        decision_text = normalize_state_to_text(
            getattr(result, "trade_decision", None),
            kind="trade_decision",
        )
        merged = "\n\n".join([
            f"## Market\n{getattr(result, 'market_report', '') or ''}",
            f"## Sentiment\n{getattr(result, 'sentiment_report', '') or ''}",
            f"## News\n{getattr(result, 'news_report', '') or ''}",
            f"## Fundamentals\n{getattr(result, 'fundamentals_report', '') or ''}",
            f"## Debate\n{debate_text}",
            f"## Risk\n{risk_text}",
            f"## Decision\n{decision_text}",
        ])

        # Phase 1 — LLM path.
        llm_dict: dict | None = None
        llm_error: str | None = None
        try:
            llm_dict = self._extract_generic("summary", OverviewCard, merged)
        except Exception as e:  # noqa: BLE001 — surface to fallback meta
            llm_error = f"{type(e).__name__}: {e}"[:200]
            logger.warning("Overview LLM extract failed: %s", llm_error)

        if isinstance(llm_dict, dict) and llm_dict:
            llm_dict.setdefault("_fallback_used", False)
            return llm_dict

        # Phase 2 — deterministic fallback.
        fallback = _build_overview_fallback(
            result,
            debate_text=debate_text,
            risk_text=risk_text,
            decision_text=decision_text,
        )
        if fallback is None:
            return None
        fallback["_fallback_used"] = True
        if llm_error:
            fallback["_fallback_error"] = llm_error
        return fallback

    # ── News (hybrid + hard guard) ───────────────────────────────────

    def _extract_news(self, result, ticker: str):
        headlines = fetch_news_headlines(ticker, self._dm)
        news_report = getattr(result, "news_report", "") or ""
        if not headlines and not news_report.strip():
            return None

        prompt = (
            "Real headlines (from data API, immutable):\n"
            f"{json.dumps(headlines, ensure_ascii=False)}\n\n"
            "LLM news_report context:\n"
            f"{news_report}"
        )
        try:
            structured = self._llm.with_structured_output(NewsCard)
            card = structured.invoke([
                {"role": "system", "content": _SYS_NEWS},
                {"role": "user",   "content": prompt},
            ])
        except Exception as e:  # noqa: BLE001
            logger.warning("News LLM enrich failed: %s", e)
            if headlines:
                return {"headlines": headlines, "catalysts": [], "summary": ""}
            return None

        # Hard guard 1: drop any LLM-emitted headline whose title doesn't
        # appear in the real-data set. The real titles are the ground truth.
        real_by_title = {h["title"]: h for h in headlines}
        merged: list[dict] = []
        seen: set[str] = set()
        if card is not None:
            for hl in (card.headlines or []):
                base = real_by_title.get(hl.title)
                if not base:
                    logger.warning(
                        "News hard guard dropped fabricated headline: %r",
                        hl.title,
                    )
                    continue
                merged.append({
                    **base,
                    "sentiment": hl.sentiment,
                    "impact": hl.impact,
                })
                seen.add(hl.title)

        # Hard guard 2: real headlines the LLM forgot to tag are appended
        # so users never lose a real-world event.
        for h in headlines:
            if h["title"] not in seen:
                merged.append(h)

        catalysts = []
        summary = ""
        if card is not None:
            catalysts = [c.model_dump(mode="json")
                         for c in (card.catalysts or [])]
            summary = card.summary or ""

        return {
            "headlines": merged,
            "catalysts": catalysts,
            "summary": summary,
        }

    # ── Fundamentals (hybrid + hard guard) ───────────────────────────

    def _extract_fundamentals(self, result, ticker: str):
        facts = fetch_fundamentals_facts(ticker, self._dm)
        fundamentals_report = getattr(result, "fundamentals_report", "") or ""
        if not facts:
            # Pure-LLM fallback (v1.0 behavior) — no data_manager available.
            return self._extract_generic(
                "Fundamentals", FundamentalsCard, fundamentals_report,
            )

        prompt = (
            "Real facts (from data API, immutable):\n"
            f"{json.dumps(facts, ensure_ascii=False)}\n\n"
            "LLM fundamentals_report context:\n"
            f"{fundamentals_report}"
        )
        try:
            structured = self._llm.with_structured_output(FundamentalsCard)
            card = structured.invoke([
                {"role": "system", "content": _SYS_FUNDAMENTALS},
                {"role": "user",   "content": prompt},
            ])
        except Exception as e:  # noqa: BLE001
            logger.warning("Fundamentals LLM enrich failed: %s", e)
            return {
                "valuation":     facts["valuation"],
                "growth":        facts["growth"],
                "profitability": facts["profitability"],
                "balance_sheet": facts["balance_sheet"],
                "quality_score": 3,
                "summary":       "",
            }

        # Hard guard: overwrite numeric blocks with real facts. Only the
        # qualitative slots (vs_industry / quality_score / summary) survive
        # from the LLM. This protects against models that "round" PE or
        # invent a friendlier debt-to-equity.
        vs_industry = None
        quality_score = 3
        summary = ""
        if card is not None:
            if card.valuation is not None and card.valuation.vs_industry:
                vs_industry = card.valuation.vs_industry
            if card.quality_score is not None:
                quality_score = int(card.quality_score)
            if card.summary:
                summary = card.summary

        return {
            "valuation": {
                **facts["valuation"],
                "vs_industry": vs_industry,
            },
            "growth":        facts["growth"],
            "profitability": facts["profitability"],
            "balance_sheet": facts["balance_sheet"],
            "quality_score": quality_score,
            "summary":       summary,
        }


# ── Deterministic Overview fallback ──────────────────────────────────────
#
# Pure helpers (no LLM, no I/O) used by ``_extract_overview`` when the
# structured-output call returns None or raises. The goal is to never
# leave the 概览 tab empty whenever any source report exists.

import re as _re  # local alias so module-level top stays tidy


def _signal_to_rating(signal: str, decision_text: str) -> str:
    """Map a free-form signal / decision blurb to an ``OverviewCard.rating``
    enum value. Returns ``Hold`` when nothing matches so the schema
    contract always holds (RatingLiteral has no permissive default)."""
    haystack = f"{signal or ''} {decision_text or ''}".lower()
    if "strong buy" in haystack or "strongly buy" in haystack:
        return "Strong Buy"
    if "strong sell" in haystack or "strongly sell" in haystack:
        return "Strong Sell"
    if "overweight" in haystack or "加仓" in haystack:
        return "Overweight"
    if "underweight" in haystack or "减仓" in haystack:
        return "Underweight"
    if "sell" in haystack or "bearish" in haystack:
        return "Sell"
    if "buy" in haystack or "bullish" in haystack:
        return "Buy"
    return "Hold"


def _first_sentences(text: str, n: int = 2, max_chars: int = 160) -> str:
    """Pull the first ``n`` sentences out of ``text``. Pragmatic split on
    Chinese / English terminators; truncates at ``max_chars``."""
    if not text:
        return ""
    cleaned = " ".join(text.strip().split())
    pieces: list[str] = []
    buf = ""
    for ch in cleaned:
        buf += ch
        if ch in "。!?！？":
            pieces.append(buf.strip())
            buf = ""
            if len(pieces) >= n:
                break
        elif ch == "." and len(buf) > 4:
            # English period — only treat as terminator if followed by
            # space (handled by the next iteration's whitespace).
            pieces.append(buf.strip())
            buf = ""
            if len(pieces) >= n:
                break
    if buf.strip() and len(pieces) < n:
        pieces.append(buf.strip())
    if not pieces:
        out = cleaned
    else:
        has_cjk = any("一" <= c <= "鿿" for c in cleaned)
        out = "".join(pieces) if has_cjk else " ".join(pieces)
    return out[:max_chars].rstrip()


def _detect_confidence(decision_text: str, debate_text: str) -> str:
    """Sniff a confidence hint out of decision / debate prose. Defaults
    to ``medium`` so the OverviewCard never lands without a value."""
    blob = f"{decision_text or ''}\n{debate_text or ''}".lower()
    if any(kw in blob for kw in ("high confidence", "very confident",
                                  "高信心", "强烈", "高度确信")):
        return "high"
    if any(kw in blob for kw in ("low confidence", "uncertain",
                                  "不确定", "信心不足")):
        return "low"
    return "medium"


_METRIC_LINE_RE = _re.compile(
    r"^\s*[-*•]?\s*([A-Za-z一-鿿][\w一-鿿 \-/()%.]*?)\s*[:：]\s*(\S.{0,80})\s*$"
)


def _key_metric_lines(reports: dict[str, str], limit: int = 4) -> list[dict]:
    """Pull a handful of ``Label: Value`` style bullets out of the market /
    fundamentals reports. Returns ``[]`` when no recognisable line is
    present (the card simply hides the section in that case)."""
    metrics: list[dict] = []
    seen: set[str] = set()
    for source in reports.values():
        if not source:
            continue
        for line in source.splitlines():
            m = _METRIC_LINE_RE.match(line)
            if not m:
                continue
            label = m.group(1).strip()[:40]
            value = m.group(2).strip()[:60]
            if not label or not value:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            metrics.append({
                "label": label,
                "value": value,
                "tone": "neutral",
                "hint": None,
            })
            if len(metrics) >= limit:
                return metrics
    return metrics


def _decision_drivers(reports: dict[str, str], limit: int = 3) -> list[dict]:
    """Build up to ``limit`` decision-driver bullets — one per non-empty
    source report — by taking each report's first sentence as the
    ``detail`` and the report's localized name as the headline."""
    drivers: list[dict] = []
    for label, text in reports.items():
        if not text or not text.strip():
            continue
        head = _first_sentences(text, n=1, max_chars=80)
        if not head:
            continue
        drivers.append({"headline": label, "detail": head})
        if len(drivers) >= limit:
            break
    return drivers


def _build_overview_fallback(
    result,
    *,
    debate_text: str,
    risk_text: str,
    decision_text: str,
) -> dict | None:
    """Build a minimal-viable ``OverviewCard`` dict deterministically.

    Returns ``None`` when every source field is empty (genuine empty
    row — the classifier should flag the whole rendering as ``empty``).
    """
    market_report = getattr(result, "market_report", "") or ""
    sentiment_report = getattr(result, "sentiment_report", "") or ""
    news_report = getattr(result, "news_report", "") or ""
    fundamentals_report = getattr(result, "fundamentals_report", "") or ""

    source_blobs = {
        "市场": market_report,
        "情绪": sentiment_report,
        "新闻": news_report,
        "基本面": fundamentals_report,
        "辩论": debate_text,
        "风险": risk_text,
        "决策": decision_text,
    }
    if not any(v.strip() for v in source_blobs.values()):
        return None

    signal = getattr(result, "signal", "") or ""
    rating = _signal_to_rating(signal, decision_text)

    action_direction = _first_sentences(decision_text, n=1, max_chars=120)
    if not action_direction:
        for blob in (market_report, fundamentals_report, sentiment_report):
            action_direction = _first_sentences(blob, n=1, max_chars=120)
            if action_direction:
                break
    if not action_direction:
        action_direction = f"维持当前评级 ({rating})"

    one_line = _first_sentences(decision_text, n=1, max_chars=140) \
        or action_direction

    return {
        "rating": rating,
        "action_direction": action_direction,
        "confidence": _detect_confidence(decision_text, debate_text),
        "key_metrics": _key_metric_lines({
            "market": market_report,
            "fundamentals": fundamentals_report,
        }),
        "debate_synthesis": None,
        "decision_drivers": _decision_drivers(source_blobs),
        "one_line_takeaway": one_line,
    }
