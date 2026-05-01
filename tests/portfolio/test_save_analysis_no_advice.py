"""save_analysis() must not persist any per-user advice on the shared row.

Bug fixed: pre-v1.16, ``PortfolioDatabase.save_analysis()`` accepted
``advice_json`` in its payload and wrote both the JSON blob *and* the
extracted structured columns (action / confidence / position_pct /
entry_low / entry_high / stop_loss / take_profit) to the shared row.
Any other reader who hit ``analysis_history`` would inherit the original
caller's holdings-aware plan.

Post-fix: ``advice_json`` is forced to "" and the structured advice
columns are forced to NULL regardless of what the caller passes. The
per-user advice path is ``save_user_advice(user_id, analysis_id, ...)``.
"""

from __future__ import annotations

import json
import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase


def test_save_analysis_strips_advice_json_payload(tmp_path):
    db_path = str(tmp_path / "p.db")
    db = PortfolioDatabase(db_path)
    payload = {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "advice_json": json.dumps({
            "action": "BUY",
            "confidence": "high",
            "suggested_position_pct": 0.05,
            "entry_price_low": 145.0,
            "entry_price_high": 150.0,
            "stop_loss": 140.0,
            "take_profit": 165.0,
        }),
        "created_by": 1,
    }
    aid = db.save_analysis(payload)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT advice_json, action, confidence, position_pct, "
            "entry_low, entry_high, stop_loss, take_profit "
            "FROM analysis_history WHERE id = ?", (aid,),
        ).fetchone()
    assert row["advice_json"] == ""
    assert row["action"] is None
    assert row["confidence"] is None
    assert row["position_pct"] is None
    assert row["entry_low"] is None
    assert row["entry_high"] is None
    assert row["stop_loss"] is None
    assert row["take_profit"] is None


def test_save_analysis_then_save_user_advice_isolated(tmp_path):
    """The supported pattern: save_analysis for the shared row, then
    save_user_advice for the requesting user's private payload."""
    db_path = str(tmp_path / "p.db")
    db = PortfolioDatabase(db_path)
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": 1,
    })
    db.save_user_advice(
        user_id=1, analysis_id=aid,
        advice={
            "action": "BUY", "stop_loss": 140.0,
            "entry_price_low": 145.0, "entry_price_high": 150.0,
            "suggested_position_pct": 0.05,
        },
        holdings_snapshot="[]",
    )
    # Alice sees her advice
    alice_adv = db.get_user_advice(1, aid)
    assert alice_adv is not None
    assert alice_adv["action"] == "BUY"
    # Bob sees nothing
    assert db.get_user_advice(2, aid) is None
    # Shared row remains advice-free
    shared = db.get_analysis_by_id(aid)
    assert shared["advice_json"] == ""
    assert shared["action"] is None
