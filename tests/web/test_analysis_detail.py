"""Cross-user advice + bookmark isolation on /api/history/<id>.

v1.14 split per-user advice off analysis_history into ``user_analysis_advice``
and per-user bookmarks into ``analysis_bookmarks``. The shared analysis row
must look the same for every logged-in user; the advice + bookmarked flag
must reflect only the requesting user's data.
"""

from __future__ import annotations

import sqlite3

import pytest


def _seed_shared_analysis(app_client, *, owner_id: int, ticker="AAPL") -> int:
    """Insert a shared analysis_history row and return its id."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-30", "signal": "BUY",
        "market_report": "shared market notes",
        "sentiment_report": "shared sentiment",
        "news_report": "", "fundamentals_report": "",
        "investment_debate": "", "risk_assessment": "",
        "trade_decision": "go long",
        "advice_json": "",  # NB: per-user advice does NOT live here in v1.14
        "model": "gemini-2.5-flash", "provider": "gemini",
        "created_by": owner_id,
        "config_hash": "deadbeef0000",
        "task_id": "fake-task",
        "duration_sec": 12.5,
    })


def test_alice_sees_her_own_advice_and_bookmark(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={
            "action": "BUY", "confidence": "high",
            "suggested_position_pct": 25.0,
            "entry_price_low": 150.0, "entry_price_high": 152.0,
            "stop_loss": 145.0, "take_profit": 170.0,
            "reasoning": "alice-only thesis",
            "risk_warning": "alice-only risk",
        },
        holdings_snapshot='[{"ticker":"AAPL","shares":10,"avg_cost":120}]',
    )
    db.set_bookmark(users.alice.id, aid, True)

    rv = alice.get(f"/api/history/{aid}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["advice"] is not None
    assert body["advice"]["action"] == "BUY"
    assert body["advice"]["reasoning"] == "alice-only thesis"
    assert body["bookmarked"] is True
    assert body["created_by_name"] == "alice"  # display_name from email prefix


def test_bob_does_not_see_alices_advice(app_client):
    """Same shared analysis row, different reader → no advice leak."""
    users = app_client["users"]
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    # Alice writes her advice + bookmark
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={"action": "BUY", "reasoning": "alice-only"},
        holdings_snapshot="[]",
    )
    db.set_bookmark(users.alice.id, aid, True)

    rv = bob.get(f"/api/history/{aid}")
    assert rv.status_code == 200
    body = rv.get_json()
    # Shared fields visible
    assert body["ticker"] == "AAPL"
    assert body["market_report"] == "shared market notes"
    # Per-user fields hidden — bob has none of his own
    assert body["advice"] in (None, {}), f"bob should see no advice, got {body['advice']!r}"
    assert body["bookmarked"] is False


def test_each_user_owns_their_bookmark_and_advice(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={"action": "BUY", "reasoning": "alice"},
        holdings_snapshot="[]",
    )
    db.save_user_advice(
        user_id=users.bob.id, analysis_id=aid,
        advice={"action": "HOLD", "reasoning": "bob"},
        holdings_snapshot="[]",
    )
    db.set_bookmark(users.bob.id, aid, True)
    db.set_bookmark(users.alice.id, aid, False)

    a_body = alice.get(f"/api/history/{aid}").get_json()
    b_body = bob.get(f"/api/history/{aid}").get_json()
    assert a_body["advice"]["action"] == "BUY"
    assert a_body["advice"]["reasoning"] == "alice"
    assert a_body["bookmarked"] is False
    assert b_body["advice"]["action"] == "HOLD"
    assert b_body["advice"]["reasoning"] == "bob"
    assert b_body["bookmarked"] is True


def test_legacy_advice_json_falls_back_when_no_per_user_row(app_client):
    """Pre-v1.14 rows that wrote advice into analysis_history.advice_json
    must still render — for the original requester only."""
    import json as _json
    aid = _seed_shared_analysis(app_client, owner_id=app_client["users"].alice.id)
    # Manually backfill legacy column to simulate a pre-v1.14 row.
    conn = sqlite3.connect(app_client["db_path"])
    conn.execute(
        "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
        (_json.dumps({"action": "SELL", "reasoning": "legacy"}), aid),
    )
    conn.commit()
    conn.close()

    alice = app_client["make_client"](
        app_client["users"].alice_email, app_client["users"].alice_password,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["advice"]["action"] == "SELL"
    assert body["advice"]["reasoning"] == "legacy"
