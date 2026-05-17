"""analysis-overview-fallback v1.0 — extractor + classifier + meta tests.

Covers:

* ``test_overview_fallback_when_llm_schema_validation_fails`` — when the
  LLM raises (or returns an invalid OverviewCard), ``_extract_overview``
  MUST emit a deterministic OverviewCard-shaped dict tagged
  ``_fallback_used=True`` instead of returning ``None``.
* ``test_summary_never_none_when_any_source_report_exists`` — even when
  ALL pure-LLM tabs fail, ``summary`` survives via the fallback path as
  long as at least one source report is non-empty.
* ``test_attach_meta_promotes_summary_source_and_failed_tabs`` —
  ``status.attach_meta`` lifts the per-tab markers into a single
  ``_meta`` block (summary_source / failed_tabs / errors) the UI
  banner consumes.
"""

from __future__ import annotations

from stock_trading_system.agents.rendering.extractor import RenderingExtractor
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
from stock_trading_system.agents.rendering.status import attach_meta, classify


class _BrokenLLM:
    """Stub LLM where structured_output raises pydantic-style validation
    errors for OverviewCard but happily returns minimal cards for the
    other schemas. Mirrors the production failure mode where the model
    emits JSON the validator rejects."""

    def __init__(self, *, fail_schemas: tuple = (OverviewCard,)):
        self._fail_schemas = set(fail_schemas)
        self.calls: list[str] = []

    def with_structured_output(self, schema):
        outer = self
        target_schema = schema

        class _S:
            def invoke(self, _msgs):
                outer.calls.append(target_schema.__name__)
                if target_schema in outer._fail_schemas:
                    raise ValueError(
                        f"forced schema validation failure for {target_schema.__name__}"
                    )
                if target_schema is MarketCard:
                    return MarketCard(
                        trend="neutral", indicators=[],
                        support_resistance=[], patterns=[], summary="ok",
                    )
                if target_schema is SentimentCard:
                    return target_schema.model_construct()
                if target_schema is NewsCard:
                    return target_schema.model_construct()
                if target_schema is FundamentalsCard:
                    return target_schema.model_construct()
                if target_schema is DebateCard:
                    return target_schema.model_construct()
                if target_schema is RiskCard:
                    return target_schema.model_construct()
                if target_schema is DecisionCard:
                    return target_schema.model_construct()
                return target_schema.model_construct()

        return _S()


class _NullLLM:
    """Stub LLM that returns ``None`` for every structured-output call —
    simulates an empty response from the provider."""

    def with_structured_output(self, _schema):
        class _S:
            def invoke(self, _msgs):
                return None
        return _S()


class _RichResult:
    """Analyzer result with realistic source reports (decision text +
    market metrics) so the deterministic fallback has something to
    extract."""
    ticker = "AAPL"
    signal = "BUY"
    market_report = (
        "RSI: 65\n"
        "MACD: bullish crossover at 1.20\n"
        "Trend: upward, holding 200-SMA support.\n"
    )
    sentiment_report = "市场情绪偏暖。机构买入意愿增强。"
    news_report = ""
    fundamentals_report = (
        "PE: 28.3\n"
        "PB: 12.4\n"
        "ROE: 138%\n"
        "营收增速保持稳健。"
    )
    investment_debate = "Bull 主张持有 6-12 个月。"
    risk_assessment = "若大盘急跌则有 15% 回撤风险。"
    trade_decision = (
        "FINAL TRANSACTION PROPOSAL: **BUY**. "
        "建议以分批方式介入，控制仓位低于 5%。"
    )


class _DecisionOnlyResult:
    """Analyzer result whose only non-empty field is ``trade_decision``.
    Mirrors a historical row that came out of an early prototype where
    Market / Sentiment / News / Fundamentals were never recorded."""
    ticker = "MSFT"
    signal = "HOLD"
    market_report = ""
    sentiment_report = ""
    news_report = ""
    fundamentals_report = ""
    investment_debate = ""
    risk_assessment = ""
    trade_decision = (
        "FINAL TRANSACTION PROPOSAL: **HOLD**. "
        "观察 30 日，无明显催化前不动手。"
    )


# ── 1 ─────────────────────────────────────────────────────────────────────
def test_overview_fallback_when_llm_schema_validation_fails():
    """LLM raises on OverviewCard → fallback dict, _fallback_used=True."""
    extractor = RenderingExtractor(_BrokenLLM(fail_schemas=(OverviewCard,)))
    summary = extractor._extract_overview(_RichResult())

    assert summary is not None, "fallback must NOT return None"
    assert summary.get("_fallback_used") is True
    # Schema-shaped fields are present.
    assert summary["rating"] in {
        "Strong Buy", "Buy", "Overweight", "Hold",
        "Underweight", "Sell", "Strong Sell",
    }
    assert summary["confidence"] in {"high", "medium", "low"}
    assert summary["action_direction"], "action_direction must be non-empty"
    assert summary["one_line_takeaway"], "one_line_takeaway must be non-empty"
    # Drivers should pull from the source reports.
    drivers = summary.get("decision_drivers") or []
    assert isinstance(drivers, list)
    assert drivers, "expected at least one decision driver from source reports"
    # Error string is preserved for operator triage.
    assert "ValueError" in summary.get("_fallback_error", "")


# ── 2 ─────────────────────────────────────────────────────────────────────
def test_summary_never_none_when_any_source_report_exists():
    """Even when every LLM call returns None, summary must come from
    the deterministic fallback as long as ANY source field is set."""
    extractor = RenderingExtractor(_NullLLM())
    out = extractor.extract(_DecisionOnlyResult(), ticker="MSFT")

    assert out["summary"] is not None, (
        "summary must always be populated when any source report exists"
    )
    assert out["summary"].get("_fallback_used") is True
    assert out["summary"]["rating"] == "Hold"
    assert "HOLD" in out["summary"]["action_direction"] \
        or "观察" in out["summary"]["action_direction"]


# ── 3 ─────────────────────────────────────────────────────────────────────
def test_summary_returns_none_when_every_source_empty():
    """Sanity bound on case 2: when EVERY source field is empty the
    fallback returns ``None`` so the classifier reports ``empty``
    (not ``failed``) and we don't waste retry tokens."""

    class _Empty:
        ticker = "X"
        signal = ""
        market_report = ""
        sentiment_report = ""
        news_report = ""
        fundamentals_report = ""
        investment_debate = ""
        risk_assessment = ""
        trade_decision = ""

    extractor = RenderingExtractor(_NullLLM())
    summary = extractor._extract_overview(_Empty())
    assert summary is None


# ── 4 ─────────────────────────────────────────────────────────────────────
def test_attach_meta_promotes_summary_source_and_failed_tabs():
    """``attach_meta`` lifts ``_fallback_used`` / ``_fallback_error`` from
    the summary card into ``rendering["_meta"]`` and lists every tab
    whose value is ``None`` in ``failed_tabs``."""
    rendering = {
        "summary": {
            "rating": "Hold",
            "action_direction": "x",
            "confidence": "medium",
            "one_line_takeaway": "x",
            "_fallback_used": True,
            "_fallback_error": "RateLimitError: 429 quota",
        },
        "Market": {"trend": "neutral"},
        "Sentiment": None,
        "News": None,
        "Fundamentals": {"summary": "y"},
        "Investment Debate": {"summary": "z"},
        "Risk Assessment": None,
        "Decision": {"final_action": "HOLD"},
    }
    attached = attach_meta(rendering)
    meta = attached["_meta"]

    assert meta["summary_source"] == "fallback"
    assert set(meta["failed_tabs"]) == {"Sentiment", "News", "Risk Assessment"}
    assert meta["errors"]["summary"].startswith("RateLimitError")

    # The classifier should consider the row "partial" — summary present
    # but Sentiment / News / Risk Assessment missing.
    status, err = classify(attached, source_tabs_present=[
        "summary", "Market", "Sentiment", "News",
        "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
    ])
    assert status == "partial"
    assert err and "missing tabs" in err


# ── 5 ─────────────────────────────────────────────────────────────────────
def test_history_detail_rendering_summary_present_for_decision_only_report():
    """Drive the full extractor + meta pipeline against a row whose only
    source is ``trade_decision`` and assert the persistence layer would
    surface a non-null summary card with `_meta.summary_source` set."""
    extractor = RenderingExtractor(_NullLLM())
    out = extractor.extract(_DecisionOnlyResult(), ticker="MSFT")
    attached = attach_meta(out)

    assert attached["summary"] is not None
    assert attached["_meta"]["summary_source"] == "fallback"
    assert "summary" not in attached["_meta"]["failed_tabs"], (
        "summary must never appear in failed_tabs when fallback succeeded"
    )
