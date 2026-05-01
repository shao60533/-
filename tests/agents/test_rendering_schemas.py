"""Pydantic schema contract tests for the v1.19 8-tab rendering."""

from __future__ import annotations

import pytest

from stock_trading_system.agents.rendering.schemas import (
    DebateSynthesis,
    DecisionCard,
    KeyMetric,
    MarketCard,
    OverviewCard,
    Stance,
    TakeProfitLevel,
    TAB_SCHEMA,
)


def test_overview_round_trip():
    card = OverviewCard(
        rating="Underweight",
        action_direction="减仓 30-40%",
        confidence="medium",
        key_metrics=[KeyMetric(label="现价", value="$61.86", tone="negative")],
        debate_synthesis=DebateSynthesis(
            aggressive=Stance(claim="a", evidence="b", limitation="c"),
            conservative=Stance(claim="a", evidence="b", limitation="c"),
            neutral=Stance(claim="a", evidence="b", limitation="c"),
            verdict="减仓锁利",
        ),
        decision_drivers=[],
        one_line_takeaway="动能衰竭, 减仓等待",
    )
    blob = card.model_dump_json()
    again = OverviewCard.model_validate_json(blob)
    assert again.rating == "Underweight"
    assert again.confidence == "medium"
    assert again.debate_synthesis is not None
    assert again.debate_synthesis.verdict == "减仓锁利"


def test_market_card_strict_rejects_unknown_trend():
    """Literal types must reject anything outside the allowed enum."""
    with pytest.raises(Exception):
        MarketCard(
            trend="up",  # ← not in the literal union
            indicators=[], support_resistance=[], patterns=[], summary="",
        )


def test_decision_card_take_profit_weight_clamped():
    """``weight_pct`` is bounded ``ge=1, le=100``."""
    with pytest.raises(Exception):
        TakeProfitLevel(price=100.0, weight_pct=200)
    with pytest.raises(Exception):
        TakeProfitLevel(price=100.0, weight_pct=0)


def test_decision_card_minimal():
    card = DecisionCard(
        final_action="BUY", conviction="high", time_horizon="swing",
        one_line_summary="enter on breakout",
    )
    assert card.final_action == "BUY"
    assert card.entry_zone is None
    assert card.preconditions == []


def test_tab_schema_keys_match_8_tabs():
    """The frontend hard-codes these 8 keys; any rename must be intentional."""
    assert set(TAB_SCHEMA.keys()) == {
        "summary", "Market", "Sentiment", "News",
        "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
    }


def test_overview_max_lengths_enforced():
    """``key_metrics`` capped at 6 to keep the KPI row a single screenful."""
    overflow = [KeyMetric(label=f"k{i}", value=str(i)) for i in range(8)]
    with pytest.raises(Exception):
        OverviewCard(
            rating="Hold", action_direction="x", confidence="low",
            key_metrics=overflow, decision_drivers=[],
            one_line_takeaway="t",
        )


def test_user_advice_fields_not_in_decision_schema():
    """Boundary check: per-user advice fields (position_pct, reasoning,
    holdings_context) are stored in ``user_analysis_advice`` and must
    NEVER appear in the shared rendering schema. Fail loud if a future
    change reintroduces them."""
    forbidden = {
        "position_pct", "user_advice", "holdings_context", "reasoning",
    }
    decision_fields = set(DecisionCard.model_fields.keys())
    leaked = forbidden & decision_fields
    assert not leaked, f"DecisionCard leaks user-private fields: {leaked}"
