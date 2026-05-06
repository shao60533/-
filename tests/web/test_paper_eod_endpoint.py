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
    assert captured == [int(alice_sess["id"])], (
        f"DailyUpdater must run against alice's session "
        f"({alice_sess['id']}), got {captured}"
    )
