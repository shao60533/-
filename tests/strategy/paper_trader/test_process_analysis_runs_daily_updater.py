"""paper-trade v1.5 verification: ``process_analysis`` MUST call
``DailyUpdater.update_session(session_id)`` after saving the plan
so the daily_stats window catches up to the latest available bar
in a single round-trip.

Regression target — the user's 2026-05-07 acceptance review noted
that NVDA / NFLX ``last_eod_date`` was stuck at 2026-04-24 even
though new analyses had landed since. Pre-v1.5 ``process_analysis``
returned without ever invoking the EOD walker; the daily tab on
``/paper-trade/<ticker>`` then showed empty stats while the
strategy tab showed an active plan + trades.

This test mocks ``DailyUpdater`` to capture the ``update_session``
call and avoid hitting yfinance / DataHelper. The contract under
test is:
    process_analysis(...) -> {ok=True, new_daily_rows=N, ...}
where ``new_daily_rows`` reflects how many EOD rows the bundled
DailyUpdater pass produced.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

from stock_trading_system.strategy.paper_trader import (
    PaperTradeStore, process_analysis,
)


def _seed_session_db(db_path: str) -> None:
    """Force-create the schema PaperTradeStore expects so we can run
    process_analysis end-to-end without a Flask app context."""
    PaperTradeStore(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, date TEXT, signal TEXT,
            created_by INTEGER
        );
        """
    )
    conn.close()


def test_process_analysis_invokes_daily_updater(tmp_path):
    """``process_analysis`` must hand the new session_id off to
    ``DailyUpdater.update_session`` exactly once, and surface the
    row count under ``new_daily_rows`` in its return value."""
    db_path = str(tmp_path / "paper.db")
    _seed_session_db(db_path)
    store = PaperTradeStore(db_path)

    captured: list[int] = []

    class _StubDailyUpdater:
        def __init__(self, *_a, **_kw):
            pass

        def update_session(self, session_id):
            captured.append(int(session_id))
            # Pretend two trading days were filled.
            return [{"date": "2026-05-06"}, {"date": "2026-05-07"}]

    # ``event_executor._sync_daily_stats`` does
    # ``from stock_trading_system.strategy.paper_trader.daily_updater
    # import DailyUpdater`` — patch at that exact path so the
    # stub is what the helper imports inside the function body.
    with patch(
        "stock_trading_system.strategy.paper_trader.daily_updater.DailyUpdater",
        _StubDailyUpdater,
    ):
        res = process_analysis(
            store,
            analysis_id=1,
            ticker="AAPL",
            analysis_date="2026-05-07",
            signal="BUY",
            advice={
                "action": "BUY",
                "entry_price_low": 188.0,
                "entry_price_high": 192.0,
                "stop_loss": 184.0,
                "suggested_position_pct": 0.10,
            },
            current_price=190.0,
            user_id=42,
        )

    assert res.get("ok") is True, f"process_analysis failed: {res!r}"
    assert res.get("new_daily_rows") == 2, (
        f"new_daily_rows must reflect bundled EOD pass; got {res!r}"
    )
    assert len(captured) == 1, (
        f"DailyUpdater.update_session must run exactly once; got {captured!r}"
    )
    assert captured[0] == int(res["session_id"]), (
        f"DailyUpdater must run against the session process_analysis "
        f"created (session_id={res['session_id']}), got {captured!r}"
    )


def test_process_analysis_swallows_daily_updater_failure(tmp_path):
    """A broken DailyUpdater MUST NOT propagate up — paper-trade
    is a side-effect of analysis, not its primary outcome.
    ``new_daily_rows`` falls back to 0 and the rest of the
    plan/order pipeline still runs cleanly."""
    db_path = str(tmp_path / "paper.db")
    _seed_session_db(db_path)
    store = PaperTradeStore(db_path)

    class _Boom:
        def __init__(self, *_a, **_kw):
            pass

        def update_session(self, session_id):
            raise RuntimeError("yfinance unreachable")

    with patch(
        "stock_trading_system.strategy.paper_trader.daily_updater.DailyUpdater",
        _Boom,
    ):
        res = process_analysis(
            store,
            analysis_id=2,
            ticker="MSFT",
            analysis_date="2026-05-07",
            signal="BUY",
            advice={
                "action": "BUY",
                "entry_price_low": 410.0,
                "entry_price_high": 420.0,
                "stop_loss": 400.0,
                "suggested_position_pct": 0.05,
            },
            current_price=415.0,
            user_id=42,
        )

    assert res.get("ok") is True, f"process_analysis must not fail: {res!r}"
    assert res.get("new_daily_rows") == 0
    # The plan + immediate-order pipeline still ran.
    assert res.get("session_id") is not None
    assert "plan_id" in res
