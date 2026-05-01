"""v1.21: ``/api/paper/tickers`` collapses legacy duplicate sessions
for the same (user, ticker) into one card.

These tests drop the v1.20 unique index in the test DB so we can simulate
the legacy production state where one user had multiple paper-trade
sessions for the same ticker.
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.strategy.paper_trader import PaperTradeStore


def _drop_unique_index(db_path: str) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute("DROP INDEX IF EXISTS idx_session_ticker_user")


def _make_dup_sessions(app_client, *, ticker: str, user_id: int) -> tuple[int, int]:
    """Create two paper-trade sessions for (user, ticker) bypassing the
    unique index. Returns (sid1, sid2)."""
    from stock_trading_system.web import app as app_module
    store: PaperTradeStore = (
        app_module._paper_store
        if app_module._paper_store is not None
        else app_module._get_paper_store()
    )
    # Force-init so the table + index exist, then drop the index.
    if store is None:
        with app_client["app"].test_request_context():
            store = app_module._get_paper_store()
    _drop_unique_index(app_client["db_path"])
    sid1 = store.create_ticker_session(
        ticker=ticker, start_date="2026-04-19",
        start_capital=10_000.0, user_id=user_id,
    )
    sid2 = store.create_ticker_session(
        ticker=ticker, start_date="2026-05-01",
        start_capital=10_000.0, user_id=user_id,
    )
    return sid1, sid2, store


# ── List endpoint aggregates ─────────────────────────────────────────────


def test_list_collapses_duplicate_sessions_to_one_card(alice_client, app_client):
    """GOOG 2026-04-19 + GOOG 2026-05-01 → one card."""
    alice_id = app_client["users"].alice.id
    sid1, sid2, _store = _make_dup_sessions(
        app_client, ticker="GOOG", user_id=alice_id,
    )
    rv = alice_client.get("/api/paper/tickers?mode=forward")
    assert rv.status_code == 200
    body = rv.get_json()
    goog = [t for t in body if t["ticker"] == "GOOG"]
    assert len(goog) == 1, body
    card = goog[0]
    # Canonical id = earliest sibling.
    assert card["id"] == sid1
    assert card["latest_session_id"] == sid2
    assert sorted(card["session_ids"]) == sorted([sid1, sid2])
    # start_date follows canonical (earliest tracked).
    assert card["start_date"] == "2026-04-19"


def test_list_sums_counters_across_siblings(alice_client, app_client):
    """history events / active plans / pending+triggered orders all
    sum across siblings — the card totals must equal historical truth."""
    alice_id = app_client["users"].alice.id
    sid1, sid2, store = _make_dup_sessions(
        app_client, ticker="GOOG", user_id=alice_id,
    )
    # 2 events on sid1, 1 on sid2 → total 3 history analyses.
    store.insert_strategy_event(
        session_id=sid1, analysis_id=1, event_date="2026-04-20",
        new_signal="BUY", action="open",
    )
    store.insert_strategy_event(
        session_id=sid1, analysis_id=2, event_date="2026-04-25",
        new_signal="BUY", action="add",
    )
    store.insert_strategy_event(
        session_id=sid2, analysis_id=3, event_date="2026-05-02",
        new_signal="HOLD", action="hold",
    )
    # 1 active plan on each sibling.
    for sid, aid in [(sid1, 1), (sid2, 3)]:
        store.save_plan(
            session_id=sid, analysis_id=aid, rating="A", thesis="t",
            holding_months=(1, 6), raw_summary="r",
            plan={"orders": [], "rating": "A", "thesis": "t"},
            parse_method="regex",
        )
    body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    card = next(t for t in body if t["ticker"] == "GOOG")
    assert card["analysis_count"] == 3
    assert card["num_events"] == 3
    assert card["active_plan_count"] == 2


def test_list_does_not_leak_other_users_sessions(
    alice_client, bob_client, app_client,
):
    """Alice has 2 GOOG sessions, Bob has 1. Alice sees 1 card; Bob
    sees a different 1 card. Cross-user data never leaks."""
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id
    a1, a2, store = _make_dup_sessions(
        app_client, ticker="GOOG", user_id=alice_id,
    )
    bob_sid = store.create_ticker_session(
        ticker="GOOG", start_date="2026-04-30",
        start_capital=10_000.0, user_id=bob_id,
    )
    a_body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    b_body = bob_client.get("/api/paper/tickers?mode=forward").get_json()
    a_goog = [t for t in a_body if t["ticker"] == "GOOG"]
    b_goog = [t for t in b_body if t["ticker"] == "GOOG"]
    assert len(a_goog) == 1
    assert len(b_goog) == 1
    # Alice's card carries her two sibling ids; Bob's only his own.
    assert sorted(a_goog[0]["session_ids"]) == sorted([a1, a2])
    assert b_goog[0]["session_ids"] == [bob_sid]
    assert a_goog[0]["id"] != b_goog[0]["id"]


def test_list_requires_login(anon_client):
    rv = anon_client.get("/api/paper/tickers?mode=forward")
    assert rv.status_code == 401


def test_list_idempotent_on_refresh(alice_client, app_client):
    """Calling the list twice must return the same single card —
    aggregation can't introduce a 3rd phantom row on re-read."""
    alice_id = app_client["users"].alice.id
    _make_dup_sessions(app_client, ticker="GOOG", user_id=alice_id)
    body1 = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    body2 = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    g1 = [t for t in body1 if t["ticker"] == "GOOG"]
    g2 = [t for t in body2 if t["ticker"] == "GOOG"]
    assert len(g1) == 1 and len(g2) == 1
    assert g1[0]["session_ids"] == g2[0]["session_ids"]


# ── Detail endpoint merges across siblings ───────────────────────────────


def test_detail_merges_events_across_siblings(alice_client, app_client):
    """Clicking the aggregated card must surface events from BOTH
    sessions, not just the canonical one."""
    alice_id = app_client["users"].alice.id
    sid1, sid2, store = _make_dup_sessions(
        app_client, ticker="GOOG", user_id=alice_id,
    )
    store.insert_strategy_event(
        session_id=sid1, analysis_id=1, event_date="2026-04-20",
        new_signal="BUY", action="open",
    )
    store.insert_strategy_event(
        session_id=sid2, analysis_id=2, event_date="2026-05-02",
        new_signal="HOLD", action="hold",
    )
    rv = alice_client.get("/api/paper/tickers/GOOG")
    assert rv.status_code == 200
    body = rv.get_json()
    assert sorted(body["session_ids"]) == sorted([sid1, sid2])
    event_dates = sorted(e["event_date"] for e in body["events"])
    assert event_dates == ["2026-04-20", "2026-05-02"]


def test_detail_merges_plans_across_siblings(alice_client, app_client):
    """``plan_history`` must include plans from every sibling."""
    alice_id = app_client["users"].alice.id
    sid1, sid2, store = _make_dup_sessions(
        app_client, ticker="GOOG", user_id=alice_id,
    )
    store.save_plan(
        session_id=sid1, analysis_id=1, rating="A", thesis="t1",
        holding_months=(1, 6), raw_summary="r",
        plan={"orders": [], "rating": "A", "thesis": "t1"},
        parse_method="regex",
    )
    store.save_plan(
        session_id=sid2, analysis_id=2, rating="B", thesis="t2",
        holding_months=(1, 3), raw_summary="r",
        plan={"orders": [], "rating": "B", "thesis": "t2"},
        parse_method="regex",
    )
    body = alice_client.get("/api/paper/tickers/GOOG").get_json()
    theses = sorted(p["thesis"] for p in body["plan_history"])
    assert theses == ["t1", "t2"]


def test_new_paper_track_reuses_canonical_session(alice_client, app_client):
    """After v1.20 the unique index prevents new dup sessions; this
    test pins that contract — submitting a fresh /api/paper/track for a
    ticker that already has a session does NOT create a 2nd row."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    alice_id = app_client["users"].alice.id
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "GOOG", "date": "2026-05-01", "signal": "BUY",
        "trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**",
        "created_by": alice_id,
    })
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY", "stop_loss": 100,
                "entry_price_low": 110, "entry_price_high": 115,
                "suggested_position_pct": 0.05},
        holdings_snapshot="[]",
    )
    # First submit creates the session.
    r1 = alice_client.post("/api/paper/track", json={"analysis_id": aid})
    assert r1.status_code == 200, r1.get_json()
    sid_first = r1.get_json()["session_id"]
    # Second submit for the same ticker reuses the same session id.
    r2 = alice_client.post("/api/paper/track", json={"analysis_id": aid})
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["session_id"] == sid_first
    # And the list endpoint shows exactly one GOOG card.
    body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    goog = [t for t in body if t["ticker"] == "GOOG"]
    assert len(goog) == 1
    assert goog[0]["session_ids"] == [sid_first]
