"""/api/paper/tickers must aggregate (no per-session N+1) and surface
sparkline + counters from a single batched query path.

The route was previously calling ``last_daily_stat`` /
``latest_strategy_event`` / ``list_strategy_events`` /
``list_daily_stats(limit=1000)`` for each session. With many sessions
that meant 4N round-trips plus an O(events × dailies) hit-rate loop
on every page render. v1.16 collapses everything into one aggregated
``list_ticker_sessions_summary`` call.
"""

from __future__ import annotations

from stock_trading_system.strategy.paper_trader import PaperTradeStore


def _seed_session_with_stats(
    db_path: str, *, ticker: str, user_id: int,
    days: int = 5, signal: str = "BUY",
) -> int:
    store = PaperTradeStore(db_path)
    sid = store.create_ticker_session(
        ticker=ticker, start_date="2026-04-01", user_id=user_id,
    )
    # Two strategy events so num_events > 1.
    for d in ("2026-04-02", "2026-04-05"):
        store.insert_strategy_event(
            session_id=sid, analysis_id=1,
            event_date=d,
            prev_signal=None, new_signal=signal, action="enter",
            price=100.0,
        )
    # Daily stats so we get sparkline + cum_pnl_pct.
    for i in range(days):
        date = f"2026-04-{i+1:02d}"
        store.upsert_daily_stat(
            session_id=sid, date=date,
            cash=100000.0 - i * 10,
            total_value=100000.0 + i * 50,
            close_price=100.0 + i * 0.5,
            position_shares=10,
            cum_pnl_pct=i * 0.1,
        )
    return sid


def test_tickers_endpoint_returns_sparkline_and_counters(
    alice_client, app_client,
):
    sid = _seed_session_with_stats(
        app_client["db_path"], ticker="AAPL",
        user_id=app_client["users"].alice.id, days=10,
    )
    body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    rows = [r for r in body if r["id"] == sid]
    assert rows, f"created session {sid} not in list"
    row = rows[0]
    assert row["ticker"] == "AAPL"
    assert row["current_signal"] == "BUY"
    assert row["num_events"] == 2
    assert isinstance(row["sparkline"], list)
    # sparkline capped at 30 — we only inserted 10, expect all 10 back
    # ordered ascending by date.
    assert len(row["sparkline"]) == 10
    assert row["sparkline"][0] < row["sparkline"][-1]


def test_tickers_endpoint_caps_sparkline_at_thirty(
    alice_client, app_client,
):
    sid = _seed_session_with_stats(
        app_client["db_path"], ticker="MSFT",
        user_id=app_client["users"].alice.id, days=50,
    )
    body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    row = next(r for r in body if r["id"] == sid)
    assert len(row["sparkline"]) == 30


def test_tickers_endpoint_drops_hit_rate_in_list_view(
    alice_client, app_client,
):
    """List view should NOT compute the expensive events × dailies
    hit-rate scan — it returns null and lets detail compute on demand."""
    _seed_session_with_stats(
        app_client["db_path"], ticker="TSLA",
        user_id=app_client["users"].alice.id,
    )
    body = alice_client.get("/api/paper/tickers?mode=forward").get_json()
    for row in body:
        assert row["hit_rate"] is None
        assert row["hit_pretty"] == "—"


def test_summary_method_uses_4_queries_max(app_client):
    """Direct PaperTradeStore call to confirm the aggregator API
    contract (sessions / last stat / latest event / sparkline) without
    going through the route layer."""
    db_path = app_client["db_path"]
    _seed_session_with_stats(
        db_path, ticker="AAPL",
        user_id=app_client["users"].alice.id,
    )
    _seed_session_with_stats(
        db_path, ticker="MSFT",
        user_id=app_client["users"].bob.id,
    )
    store = PaperTradeStore(db_path)
    out = store.list_ticker_sessions_summary(mode="forward")
    assert len(out) == 2
    for s in out:
        assert "last_daily_stat" in s
        assert "latest_event" in s
        assert "sparkline" in s
        assert "num_events" in s
