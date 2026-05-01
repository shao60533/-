"""SNDK-style production regression: stored ``signal=Hold`` but
``trade_decision`` opens with ``最终评级：Sell（卖出）``. The detail
DTO must surface ``decision_action='Sell'`` + ``signal_mismatch=true``
so the frontend can correct the badge and show a "已校正" hint.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase


def _seed_legacy_signal(app_client, *, signal: str, trade_decision: str) -> int:
    """Insert a row directly so we can simulate a pre-v1.16 record where
    ``signal`` and ``trade_decision`` disagree."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "SNDK", "date": "2026-04-15", "signal": signal,
        "trade_decision": trade_decision,
        "created_by": app_client["users"].alice.id,
    })
    return aid


def test_chinese_final_rating_overrides_stored_hold(alice_client, app_client):
    aid = _seed_legacy_signal(
        app_client,
        signal="Hold",
        trade_decision=(
            "最终评级：Sell（卖出）\n"
            "最终交易决策：Sell（卖出）\n"
            "Reasoning: pricing pressure ..."
        ),
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["signal"] == "Hold"            # stored row preserved
    assert body["decision_action"] == "Sell"   # canonical override
    assert body["signal_mismatch"] is True


def test_consistent_row_no_mismatch_flag(alice_client, app_client):
    """Row whose stored signal already matches trader text → no flag."""
    aid = _seed_legacy_signal(
        app_client,
        signal="Buy",
        trade_decision="FINAL TRANSACTION PROPOSAL: **BUY**",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Buy"
    assert body["signal_mismatch"] is False


def test_no_extractable_action_falls_back_to_stored_signal(
    alice_client, app_client,
):
    """Trader text without a parseable verdict (e.g. just analyst
    commentary) → decision_action=None, no mismatch flag."""
    aid = _seed_legacy_signal(
        app_client,
        signal="Hold",
        trade_decision="The market remains uncertain; will continue monitoring.",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["signal"] == "Hold"
    assert body["decision_action"] is None
    assert body["signal_mismatch"] is False


def test_chinese_buy_overrides_stored_neutral(alice_client, app_client):
    aid = _seed_legacy_signal(
        app_client,
        signal="Hold",
        trade_decision="经过多空辩论，最终交易决策：买入。",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Buy"
    assert body["signal_mismatch"] is True


def test_english_final_rating_plain_prose(alice_client, app_client):
    """Non-bold English `Final Rating: Sell` (no markdown) — common in
    GPT plain-text reports."""
    aid = _seed_legacy_signal(
        app_client,
        signal="Hold",
        trade_decision="Detailed thesis ...\nFinal Rating: Sell\n\nNotes ...",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Sell"
    assert body["signal_mismatch"] is True
