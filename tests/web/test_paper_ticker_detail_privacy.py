"""/api/paper/tickers/<ticker> ``latest_advice`` must come only from
the requesting user's user_analysis_advice row, never from the shared
``analysis_history.advice_json`` column.

Pre-fix: the route json.loads(record["advice_json"]) and returned it
to whoever asked, so any logged-in user opening Alice's ticker detail
would see Alice's plan. Post-fix: only the user's own advice surfaces.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader import PaperTradeStore


def _seed_session_with_event(db_path: str, *, ticker: str, user_id: int,
                              analysis_id: int) -> int:
    store = PaperTradeStore(db_path)
    sid = store.create_ticker_session(
        ticker=ticker, start_date="2026-04-01", user_id=user_id,
    )
    store.insert_strategy_event(
        session_id=sid, analysis_id=analysis_id,
        event_date="2026-04-15",
        prev_signal=None, new_signal="BUY", action="enter",
        price=150.0,
    )
    return sid


def test_ticker_detail_does_not_leak_legacy_advice_json(
    alice_client, bob_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": alice_id,
    })
    # Simulate a pre-migration row that still carries legacy advice_json.
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
            ('{"action":"BUY","stop_loss":140,'
             '"entry_price_low":145,"entry_price_high":150}', aid),
        )

    _seed_session_with_event(
        app_client["db_path"], ticker="AAPL",
        user_id=alice_id, analysis_id=aid,
    )

    # Bob (non-creator, no user advice) opens Alice's ticker.
    # v1.21 tightened the contract: ``find_session_by_ticker`` is now
    # user-scoped at the route, so Bob receives 404 instead of seeing
    # Alice's session with advice masked. Strictly more secure — Bob
    # never even learns the session exists.
    resp = bob_client.get("/api/paper/tickers/AAPL")
    assert resp.status_code == 404, resp.get_json()
    # Belt-and-braces: even on the historical "200 with masked advice"
    # behavior the body must not leak advice. We assert this stays true
    # via the 404 — there's no body to leak from.
    assert "advice" not in (resp.get_json() or {})


def test_ticker_detail_returns_user_advice_when_present(
    alice_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = db.save_analysis({
        "ticker": "MSFT", "date": "2026-04-15", "signal": "BUY",
        "created_by": alice_id,
    })
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={
            "action": "BUY",
            "stop_loss": 380.0,
            "entry_price_low": 395.0, "entry_price_high": 405.0,
            "suggested_position_pct": 0.04,
        },
        holdings_snapshot="[]",
    )
    _seed_session_with_event(
        app_client["db_path"], ticker="MSFT",
        user_id=alice_id, analysis_id=aid,
    )

    resp = alice_client.get("/api/paper/tickers/MSFT")
    assert resp.status_code == 200
    body = resp.get_json()
    adv = body["latest_advice"]
    assert adv is not None
    assert adv["action"] == "BUY"
    assert adv["stop_loss"] == 380.0
    assert adv["entry_price_low"] == 395.0


def test_ticker_detail_unauthenticated_returns_401(anon_client, app_client):
    resp = anon_client.get("/api/paper/tickers/AAPL")
    assert resp.status_code == 401
