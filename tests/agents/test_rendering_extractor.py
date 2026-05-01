"""Per-tab failure isolation + serialization for the rendering extractor."""

from __future__ import annotations

from stock_trading_system.agents.rendering.extractor import RenderingExtractor
from stock_trading_system.agents.rendering.schemas import (
    DebateSynthesis,
    KeyMetric,
    MarketCard,
    OverviewCard,
    Stance,
)


class _StubLLM:
    """LangChain-shaped stub LLM — every ``with_structured_output(schema)``
    returns an invoker that picks a hard-coded valid instance for the two
    schemas the test exercises directly. Other schemas use
    ``model_construct`` to skip validation."""

    def __init__(self, fail_keys: tuple[str, ...] = ()):
        self._fail_keys = set(fail_keys)
        self.calls: list[str] = []

    def with_structured_output(self, schema):
        outer = self

        class _S:
            def invoke(self, msgs):
                content = msgs[-1]["content"]
                key = content.split("[REPORT — ", 1)[1].split("]", 1)[0]
                outer.calls.append(key)
                if key in outer._fail_keys:
                    raise RuntimeError(f"forced fail {key}")
                if schema is OverviewCard:
                    return OverviewCard(
                        rating="Hold", action_direction="观察",
                        confidence="low",
                        key_metrics=[KeyMetric(label="x", value="y")],
                        debate_synthesis=DebateSynthesis(
                            aggressive=Stance(claim="a", evidence="b", limitation="c"),
                            conservative=Stance(claim="a", evidence="b", limitation="c"),
                            neutral=Stance(claim="a", evidence="b", limitation="c"),
                            verdict="v",
                        ),
                        decision_drivers=[],
                        one_line_takeaway="t",
                    )
                if schema is MarketCard:
                    return MarketCard(
                        trend="neutral", indicators=[],
                        support_resistance=[], patterns=[], summary="ok",
                    )
                # Other schemas: skip strict validation for the test stub.
                return schema.model_construct()

        return _S()


class _Result:
    market_report = "m"
    sentiment_report = "s"
    news_report = "n"
    fundamentals_report = "f"
    investment_debate = "d"
    risk_assessment = "r"
    trade_decision = "dec"


def test_extractor_returns_8_keys():
    out = RenderingExtractor(_StubLLM()).extract(_Result())
    assert set(out.keys()) == {
        "summary", "Market", "Sentiment", "News",
        "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
    }
    assert out["summary"]["rating"] == "Hold"
    assert out["Market"]["trend"] == "neutral"


def test_extractor_per_tab_failure_isolated():
    out = RenderingExtractor(_StubLLM(fail_keys=("News",))).extract(_Result())
    assert out["News"] is None
    assert out["summary"] is not None
    assert out["Market"] is not None


def test_extractor_skips_empty_input():
    class _Empty:
        market_report = ""
        sentiment_report = ""
        news_report = ""
        fundamentals_report = ""
        investment_debate = ""
        risk_assessment = ""
        trade_decision = ""

    out = RenderingExtractor(_StubLLM()).extract(_Empty())
    # summary still has joined non-empty headings — but each per-tab call
    # with empty content returns None. Verify the per-tab side.
    assert out["Market"] is None
    assert out["News"] is None
    assert out["Fundamentals"] is None


def test_extractor_serializes_to_dict_with_mode_json():
    """Returned dict must be JSON-safe (mode='json' on Pydantic dump) so
    workers can ``json.dumps`` it without custom encoders."""
    import json as _json

    out = RenderingExtractor(_StubLLM()).extract(_Result())
    blob = _json.dumps(out, ensure_ascii=False)
    again = _json.loads(blob)
    assert again["summary"]["rating"] == "Hold"
