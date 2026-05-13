"""paper-trade v1.5: /api/paper/tickers/<ticker>/eod authentication +
user-scoping contract.

Pre-fix the endpoint had no @login_required and called
``find_session_by_ticker(ticker.upper())`` without ``user_id`` —
when two users tracked the same ticker, the manual EOD button on
Alice's detail page could update Bob's older session, leaving
Alice's UI empty even after a successful 200.
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader import (
    PaperTradeStore, ensure_ticker_session,
)


def test_eod_endpoint_requires_login(anon_client):
    """Anonymous client must NOT be able to mutate any session's
    last_eod_date — the endpoint either returns 401 (our explicit
    guard) or whatever shape the global auth middleware uses for
    unauthenticated POSTs. We only assert the status code so the
    test stays compatible with either auth-error envelope."""
    resp = anon_client.post("/api/paper/tickers/AAPL/eod", json={})
    assert resp.status_code in (401, 403), (
        f"unauthenticated POST must be rejected; got {resp.status_code}: "
        f"{resp.get_data(as_text=True)}"
    )


def test_eod_endpoint_404_when_no_session_for_user(alice_client, app_client):
    """Even when a session exists for ANOTHER user, an Alice EOD call
    against the same ticker MUST return 404 — never silently update
    the other user's row."""
    bob_id = app_client["users"].bob.id
    store = PaperTradeStore(app_client["db_path"])
    # Bob has a session for AAPL.
    ensure_ticker_session(store, "AAPL", start_date="2026-04-15", user_id=bob_id)

    resp = alice_client.post("/api/paper/tickers/AAPL/eod", json={})
    assert resp.status_code == 404, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == "Not found"


def test_eod_endpoint_targets_current_user_session(monkeypatch,
                                                    alice_client, app_client):
    """Alice's EOD call MUST update Alice's session, not Bob's, even
    when both share the ticker. We assert via DailyUpdater.update_session
    receiving Alice's session_id."""
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id
    store = PaperTradeStore(app_client["db_path"])
    bob_sess = ensure_ticker_session(store, "AAPL",
                                      start_date="2026-04-15", user_id=bob_id)
    alice_sess = ensure_ticker_session(store, "AAPL",
                                        start_date="2026-04-15", user_id=alice_id)
    assert alice_sess["id"] != bob_sess["id"]

    captured: list[int] = []

    class _Stub:
        def __init__(self, *_a, **_kw):
            pass

        def update_session(self, session_id):
            captured.append(int(session_id))
            return []

    monkeypatch.setattr(
        "stock_trading_system.strategy.paper_trader.DailyUpdater",
        _Stub,
    )

    resp = alice_client.post("/api/paper/tickers/AAPL/eod", json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    assert body["session_id"] == int(alice_sess["id"])
    # New post-fix fields — session_ids enumerates every sibling row
    # the endpoint touched. Alice has exactly 1 session for AAPL here.
    assert body["session_ids"] == [int(alice_sess["id"])]
    assert captured == [int(alice_sess["id"])], (
        f"DailyUpdater must run against alice's session "
        f"({alice_sess['id']}), got {captured}"
    )
    # bob_sess belongs to another user — must NOT be touched.
    assert int(bob_sess["id"]) not in captured


def test_eod_endpoint_updates_all_sibling_sessions_for_one_user(
    monkeypatch, alice_client, app_client,
):
    """Legacy DBs may carry duplicate (user, ticker) sessions from
    before the UNIQUE index landed. Manual EOD must update EVERY
    sibling id, not just the first one — otherwise the detail page
    (which aggregates sibling sessions) shows stale rows."""
    alice_id = app_client["users"].alice.id
    store = PaperTradeStore(app_client["db_path"])
    primary = ensure_ticker_session(store, "MSFT",
                                     start_date="2026-04-15",
                                     user_id=alice_id)
    # Warm the Flask-side singleton PaperTradeStore so its
    # ``_init_schema`` runs BEFORE we introduce the duplicate row —
    # otherwise the next request would try to re-create the unique
    # index and hit IntegrityError on the legacy row we're about to
    # plant.
    warm = alice_client.get("/api/paper/tickers?mode=forward")
    assert warm.status_code == 200, warm.get_data(as_text=True)
    # Force a second sibling row via direct INSERT to mimic a legacy
    # DB carrying duplicate (ticker, user_id) rows from before the
    # ``idx_session_ticker_user`` unique index landed. Drop the index
    # for this fixture so the second INSERT succeeds.
    with store._conn() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_session_ticker_user")
        cur = conn.execute(
            """INSERT INTO paper_trade_sessions
               (name, mode, status, start_capital, start_date,
                config_json, auto_track, is_system, ticker, user_id,
                created_at)
               VALUES ('MSFT legacy', 'ticker', 'running', 100000,
                       '2026-04-10', '{}', 0, 0, 'MSFT', ?, datetime('now'))""",
            (alice_id,),
        )
        legacy_id = int(cur.lastrowid)
    assert legacy_id != int(primary["id"])

    captured: list[int] = []

    class _Stub:
        def __init__(self, *_a, **_kw): pass
        def update_session(self, session_id, target_date=None):
            captured.append(int(session_id))
            return [{"date": "2026-05-14", "total_value": 100_000}]

    monkeypatch.setattr(
        "stock_trading_system.strategy.paper_trader.DailyUpdater",
        _Stub,
    )

    resp = alice_client.post("/api/paper/tickers/MSFT/eod", json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    # Both sibling ids should appear in session_ids AND in the captured
    # update_session calls.
    assert set(body["session_ids"]) == {int(primary["id"]), legacy_id}
    assert set(captured) == {int(primary["id"]), legacy_id}
    assert body["new_rows"] == 2  # one row per session
    assert body["updated_sessions"] == 2
    assert body["latest_date"] == "2026-05-14"
