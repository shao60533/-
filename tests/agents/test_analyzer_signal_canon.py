"""Analyzer signal-canonicalization (v1.20).

Verifies that the ``signal`` field on ``AnalysisResult`` is overridden
by the trader's explicit ``FINAL TRANSACTION PROPOSAL: **X**`` whenever
the upstream ``graph.process_signal`` LLM call returns something
different. This prevents the "顶部 Hold, 决策正文 Sell" inconsistency.

The analyzer's ``analyze()`` is wrapped around the TradingAgents graph
which we don't exercise here. We instead test the module-level
``_canonical_signal`` helper that both call sites use.
"""

from __future__ import annotations

from stock_trading_system.agents.analyzer import _canonical_signal


def test_trade_decision_sell_overrides_hold_fallback():
    """``graph.process_signal`` said HOLD; trader text said SELL —
    the canonical signal must follow the trader."""
    text = "Long thesis here.\n\nFINAL TRANSACTION PROPOSAL: **SELL**"
    assert _canonical_signal(text, fallback="HOLD") == "Sell"


def test_trade_decision_hold_overrides_buy_fallback():
    text = "FINAL TRANSACTION PROPOSAL: **HOLD**"
    assert _canonical_signal(text, fallback="BUY") == "Hold"


def test_trade_decision_buy_overrides_sell_fallback():
    text = "FINAL TRANSACTION PROPOSAL: **BUY**"
    assert _canonical_signal(text, fallback="SELL") == "Buy"


def test_unparseable_decision_keeps_fallback():
    """When ``trade_decision`` has no recognisable proposal, fall back
    to whatever ``graph.process_signal`` returned (typically OVERWEIGHT
    / UNDERWEIGHT, which extract_trade_action intentionally doesn't
    classify)."""
    text = "Mixed picture. Watch for the next earnings print."
    assert _canonical_signal(text, fallback="OVERWEIGHT") == "OVERWEIGHT"


def test_dict_trade_decision_parses():
    """``final_trade_decision`` from TradingAgents is sometimes a dict
    payload — the canon path must still extract the action."""
    blob = {"trade_decision": "FINAL TRANSACTION PROPOSAL: **SELL**"}
    assert _canonical_signal(blob, fallback="HOLD") == "Sell"


def test_other_report_sections_do_not_leak():
    """Even with chatty intermediate proposals scattered across the
    pipeline, only the trader's final text drives the canonical action.
    Other reports (fundamentals / news) are not passed in here at all
    — the helper takes a single ``trade_decision`` argument by design."""
    decision = "FINAL TRANSACTION PROPOSAL: **HOLD**"
    # Even an aggressive fallback doesn't override a clean HOLD.
    assert _canonical_signal(decision, fallback="BUY") == "Hold"
