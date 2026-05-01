"""v1.20: canonical trade-action parser used to keep the detail page's
``signal`` aligned with the trader's explicit ``FINAL TRANSACTION
PROPOSAL: **X**`` text. Tests ensure intermediate / aspirational
mentions in other report sections never leak through as the final
action."""

from __future__ import annotations

from stock_trading_system.agents.iterative.signal_extractor import (
    extract_trade_action,
)


# ── Canonical FINAL TRANSACTION PROPOSAL pattern ─────────────────────────

def test_buy_proposal_recovers_buy():
    text = "Some thesis text.\n\nFINAL TRANSACTION PROPOSAL: **BUY**"
    assert extract_trade_action(text) == "Buy"


def test_sell_proposal_recovers_sell():
    text = "FINAL TRANSACTION PROPOSAL: **SELL**\n\nReasoning..."
    assert extract_trade_action(text) == "Sell"


def test_hold_proposal_recovers_hold():
    text = "Long-form analysis.\n\nFINAL TRANSACTION PROPOSAL: **HOLD**"
    assert extract_trade_action(text) == "Hold"


def test_proposal_without_bold_still_parses():
    text = "FINAL TRANSACTION PROPOSAL: BUY\nrest of the body"
    assert extract_trade_action(text) == "Buy"


def test_proposal_lowercase_keyword_parses():
    text = "final transaction proposal: **sell**"
    assert extract_trade_action(text) == "Sell"


def test_last_proposal_wins_when_multiple_present():
    """Trader memos sometimes include a draft proposal earlier in the
    text (e.g., echoing the bull thesis) and finalize differently."""
    text = (
        "Earlier draft: FINAL TRANSACTION PROPOSAL: **BUY**\n\n"
        "After risk review: FINAL TRANSACTION PROPOSAL: **HOLD**"
    )
    assert extract_trade_action(text) == "Hold"


# ── Bold-token fallback (no FINAL PROPOSAL header) ───────────────────────

def test_bold_token_without_proposal_header():
    text = "Trader sums up: **SELL** the position now."
    assert extract_trade_action(text) == "Sell"


def test_prose_keyword_alone_does_not_match():
    """Plain ``buy`` / ``sell`` / ``hold`` words inside prose must NOT
    flip the canonical action — too many false positives ("buy-side
    analysts", "sell-off risk", "long holding period")."""
    text = (
        "Buy-side analysts have been positive while sell-off risk "
        "remains. Holding period: 3-6 months. No actionable proposal."
    )
    assert extract_trade_action(text) is None


# ── Dict shape (final_trade_decision from TradingAgents) ─────────────────

def test_dict_with_trade_decision_key():
    blob = {"trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**"}
    assert extract_trade_action(blob) == "Buy"


def test_dict_with_content_key():
    blob = {"content": "FINAL TRANSACTION PROPOSAL: **HOLD**"}
    assert extract_trade_action(blob) == "Hold"


def test_dict_falls_back_to_json_dump():
    """Even when the proposal is buried in a nested messages list, the
    ``json.dumps`` fallback exposes it to the regex."""
    blob = {"messages": [{"role": "trader",
                            "content": "FINAL TRANSACTION PROPOSAL: **SELL**"}]}
    assert extract_trade_action(blob) == "Sell"


# ── Edge cases ───────────────────────────────────────────────────────────

def test_empty_string_returns_none():
    assert extract_trade_action("") is None


def test_none_input_returns_none():
    assert extract_trade_action(None) is None


def test_whitespace_only_returns_none():
    assert extract_trade_action("   \n  \n  ") is None


def test_unrelated_text_returns_none():
    assert extract_trade_action("This week's macro outlook is uncertain.") is None


# ── Cross-section contamination guard ────────────────────────────────────

def test_buy_in_fundamentals_does_not_override_sell_in_decision():
    """Reports often contain BUY/SELL stage proposals from individual
    analysts; only the trader's *final* decision counts. The DTO calls
    extract_trade_action on ``trade_decision`` only — never on
    ``fundamentals_report`` / ``news_report`` — so even if those say
    BUY, the trader's SELL stays canonical."""
    trade_decision = "FINAL TRANSACTION PROPOSAL: **SELL**"
    # Sanity: parsing the trader text in isolation gives SELL; other
    # report sections are out of scope by construction.
    assert extract_trade_action(trade_decision) == "Sell"
    # Spot-check that a report section's BUY mention parses as None
    # (no FINAL PROPOSAL header, no bold token in prose).
    fundamentals = "PE 20x suggests buy. Quality is high."
    assert extract_trade_action(fundamentals) is None
