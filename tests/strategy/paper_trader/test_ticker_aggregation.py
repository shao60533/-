"""v1.21: ``list_ticker_sessions_summary`` collapses legacy duplicate
sessions for the same ``(user_id, ticker)`` so the /paper-trade list
view shows one card per ticker. Pre-v1.20 the unique index didn't
exist, so accounts can carry several rows per ticker; we aggregate
them at read time without touching historical data."""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.strategy.paper_trader import PaperTradeStore


def _drop_unique_index(db_path: str) -> None:
    """Disable the v1.20 unique index so tests can simulate legacy
    duplicate rows for the same (user, ticker)."""
    with sqlite3.connect(db_path) as c:
        c.execute("DROP INDEX IF EXISTS idx_session_ticker_user")


def _seed_session(store: PaperTradeStore, *, ticker: str, user_id: int,
                   start_date: str, start_capital: float = 10_000.0) -> int:
    return store.create_ticker_session(
        ticker=ticker, start_date=start_date,
        start_capital=start_capital, user_id=user_id,
    )


@pytest.fixture
def store(tmp_path):
    s = PaperTradeStore(str(tmp_path / "p.db"))
    _drop_unique_index(str(tmp_path / "p.db"))
    return s


# ── Aggregation ──────────────────────────────────────────────────────────

def test_two_sessions_same_user_same_ticker_collapse_to_one(store):
    """Two GOOG sessions for alice → one card with both ids in
    ``session_ids``. No card duplication, no data loss."""
    sid1 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-04-19")
    sid2 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-05-01")
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    assert len(summaries) == 1
    s = summaries[0]
    assert s["ticker"] == "GOOG"
    # Canonical id = earliest session.
    assert int(s["id"]) == sid1
    assert s["latest_session_id"] == sid2
    assert sorted(s["session_ids"]) == sorted([sid1, sid2])
    # start_date follows canonical (earliest tracked).
    assert s["start_date"] == "2026-04-19"


def test_counters_summed_across_siblings(store):
    """active_plan_count / pending_orders_count / triggered_orders_count
    / num_events sum across all siblings — not max, not first."""
    sid1 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-04-19")
    sid2 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-05-01")
    # Two events on sid1, one on sid2.
    store.insert_strategy_event(
        session_id=sid1, analysis_id=101, event_date="2026-04-20",
        new_signal="BUY", action="open",
    )
    store.insert_strategy_event(
        session_id=sid1, analysis_id=102, event_date="2026-04-25",
        new_signal="BUY", action="add",
    )
    store.insert_strategy_event(
        session_id=sid2, analysis_id=103, event_date="2026-05-02",
        new_signal="HOLD", action="hold",
    )
    # One active plan on sid1, two on sid2.
    for sid, aid in [(sid1, 101), (sid2, 102), (sid2, 103)]:
        store.save_plan(
            session_id=sid, analysis_id=aid, rating="A",
            thesis="t", holding_months=(1, 6), raw_summary="r",
            plan={"orders": [], "rating": "A", "thesis": "t"},
            parse_method="regex",
        )
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    assert len(summaries) == 1
    s = summaries[0]
    # save_plan supersedes prior active plan within a session, so each
    # sibling has at most 1 active. Sum = 2.
    assert s["active_plan_count"] == 2
    assert s["num_events"] == 3


def test_user_scoping_keeps_other_users_invisible(store):
    """Alice's GOOG and Bob's GOOG are different cards. With user_id=1
    we never see Bob's session even though it shares the ticker."""
    a1 = _seed_session(store, ticker="GOOG", user_id=1,
                        start_date="2026-04-19")
    _b1 = _seed_session(store, ticker="GOOG", user_id=2,
                         start_date="2026-04-19")
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    assert len(summaries) == 1
    assert int(summaries[0]["id"]) == a1
    # Bob sees only his own.
    summaries_bob = store.list_ticker_sessions_summary(user_id=2, mode="forward")
    assert len(summaries_bob) == 1
    assert int(summaries_bob[0]["id"]) != a1


def test_no_session_returns_empty(store):
    assert store.list_ticker_sessions_summary(user_id=1, mode="forward") == []


def test_distinct_tickers_stay_distinct(store):
    """Aggregation is keyed on (user, ticker). AAPL and GOOG never merge."""
    _seed_session(store, ticker="AAPL", user_id=1, start_date="2026-04-19")
    _seed_session(store, ticker="GOOG", user_id=1, start_date="2026-04-19")
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    tickers = sorted(s["ticker"] for s in summaries)
    assert tickers == ["AAPL", "GOOG"]


def test_status_running_when_any_sibling_has_active_plan(store):
    """If ANY sibling carries an active plan, the aggregated card is
    'running' even when the canonical session was completed."""
    sid1 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-04-19")
    sid2 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-05-01")
    # Mark sid1 completed in DB.
    store.update_session(sid1, status="completed")  # type: ignore[attr-defined]
    # sid2 still has an active plan.
    store.save_plan(
        session_id=sid2, analysis_id=1, rating="A", thesis="t",
        holding_months=(1, 6), raw_summary="r",
        plan={"orders": [], "rating": "A", "thesis": "t"},
        parse_method="regex",
    )
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    assert summaries[0]["status"] == "running"


def test_aggregate_ticker_session_ids_returns_all_siblings(store):
    """The detail endpoint uses this helper to fan out across siblings
    when fetching events / plans / orders."""
    sid1 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-04-19")
    sid2 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-05-01")
    sid3 = _seed_session(store, ticker="AAPL", user_id=1,
                         start_date="2026-04-19")
    ids = store.aggregate_ticker_session_ids("GOOG", user_id=1)
    assert ids == sorted([sid1, sid2])
    # AAPL stays separate.
    assert sid3 not in ids


def test_group_by_ticker_false_returns_per_session(store):
    """Escape hatch: legacy callers that need per-session rows."""
    _seed_session(store, ticker="GOOG", user_id=1, start_date="2026-04-19")
    _seed_session(store, ticker="GOOG", user_id=1, start_date="2026-05-01")
    rows = store.list_ticker_sessions_summary(
        user_id=1, mode="forward", group_by_ticker=False,
    )
    assert len(rows) == 2


def test_unique_index_prevents_new_dups_when_present(tmp_path):
    """Sanity: with the v1.20 unique index in place (default), trying
    to insert a second session for the same (user, ticker) raises.
    This is why dup sessions only exist on legacy data, not new writes."""
    s = PaperTradeStore(str(tmp_path / "fresh.db"))
    s.create_ticker_session(ticker="GOOG", start_date="2026-04-19",
                             start_capital=10_000.0, user_id=1)
    with pytest.raises(sqlite3.IntegrityError):
        s.create_ticker_session(ticker="GOOG", start_date="2026-05-01",
                                 start_capital=10_000.0, user_id=1)


def test_latest_event_picks_newest_across_siblings(store):
    """The aggregated card's ``latest_event`` follows the most recent
    event by date, regardless of which sibling holds it."""
    sid1 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-04-19")
    sid2 = _seed_session(store, ticker="GOOG", user_id=1,
                         start_date="2026-05-01")
    # Older event on sid2, newer on sid1 — verify date wins, not sibling order.
    store.insert_strategy_event(
        session_id=sid2, analysis_id=1, event_date="2026-04-30",
        new_signal="BUY", action="open",
    )
    store.insert_strategy_event(
        session_id=sid1, analysis_id=2, event_date="2026-05-05",
        new_signal="SELL", action="close",
    )
    summaries = store.list_ticker_sessions_summary(user_id=1, mode="forward")
    evt = summaries[0]["latest_event"]
    assert evt is not None
    assert evt["event_date"] == "2026-05-05"
    assert evt["new_signal"] == "SELL"
