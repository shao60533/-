"""Paper backfill must read each user's private advice, never the
legacy ``analysis_history.advice_json`` blob.

Pre-fix: ``backfill._backfill_ticker`` parsed advice from the shared
row, so Bob's backfill of Alice's analyses inherited Alice's
holdings-aware entry/stop/take-profit. Post-fix: backfill reads only
``user_analysis_advice`` keyed on the explicit ``user_id`` passed in,
and falls back to a conservative shared-only plan when no per-user
advice exists.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader.backfill import (
    _resolve_user_advice,
)


def _seed_legacy_advice_row(db_path: str, *, ticker: str, date: str,
                              created_by: int, advice_json: str) -> int:
    """Simulate a pre-migration row that still carries advice_json on
    the shared analysis_history (post-v1.16 ``save_analysis`` strips it).
    """
    db = PortfolioDatabase(db_path)
    aid = db.save_analysis({
        "ticker": ticker, "date": date, "signal": "BUY",
        "created_by": created_by,
    })
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
            (advice_json, aid),
        )
    return aid


def test_backfill_resolves_only_user_private_advice(tmp_path):
    """Bob requesting backfill of Alice's analysis must NOT inherit
    Alice's legacy advice_json. He gets None (the executor will plan
    from shared signal/trade_decision text only)."""
    db_path = str(tmp_path / "p.db")
    aid = _seed_legacy_advice_row(
        db_path, ticker="AAPL", date="2026-04-01",
        created_by=1,  # alice
        advice_json='{"action":"BUY","stop_loss":140,'
                    '"suggested_position_pct":0.10,'
                    '"entry_price_low":145,"entry_price_high":150}',
    )
    db = PortfolioDatabase(db_path)

    # Bob (user_id=2) — no user advice for him, must see nothing.
    bob_adv = _resolve_user_advice(db, user_id=2, analysis_id=aid)
    assert bob_adv is None

    # CLI/cron path (user_id=None) must not silently inherit either.
    anon_adv = _resolve_user_advice(db, user_id=None, analysis_id=aid)
    assert anon_adv is None


def test_backfill_returns_user_advice_when_present(tmp_path):
    db_path = str(tmp_path / "p.db")
    aid = _seed_legacy_advice_row(
        db_path, ticker="AAPL", date="2026-04-01",
        created_by=1,
        advice_json='{"action":"BUY","stop_loss":140}',
    )
    db = PortfolioDatabase(db_path)
    db.save_user_advice(
        user_id=1, analysis_id=aid,
        advice={
            "action": "BUY",
            "stop_loss": 138.5,
            "entry_price_low": 142.0, "entry_price_high": 148.0,
            "suggested_position_pct": 0.04,
        },
        holdings_snapshot="[]",
    )
    adv = _resolve_user_advice(db, user_id=1, analysis_id=aid)
    assert adv is not None
    # Alice's private values, not the legacy advice_json's 140 stop.
    assert adv["action"] == "BUY"
    assert adv["stop_loss"] == 138.5
    assert adv["entry_price_low"] == 142.0
    assert adv["suggested_position_pct"] == 0.04


def test_backfill_all_threads_user_id_into_executor(tmp_path):
    """End-to-end: backfill_all(..., user_id=42) propagates the user
    context into process_analysis so each ticker session is per-user
    and advice resolution uses get_user_advice(42, ...)."""
    from stock_trading_system.strategy.paper_trader.backfill import (
        backfill_all,
    )
    db_path = str(tmp_path / "p.db")
    pdb = PortfolioDatabase(db_path)
    pdb.save_analysis({
        "ticker": "AAPL", "date": "2026-04-01", "signal": "BUY",
        "created_by": 42,
    })
    with patch(
        "stock_trading_system.strategy.paper_trader.backfill.process_analysis"
    ) as mock_proc, patch(
        "stock_trading_system.strategy.paper_trader.backfill.ensure_ticker_session"
    ) as mock_sess, patch(
        "stock_trading_system.strategy.paper_trader.backfill.DailyUpdater"
    ) as mock_upd:
        mock_sess.return_value = {"id": 1}
        mock_upd.return_value._fetch_bars.return_value = None
        mock_upd.return_value._process_day.return_value = None
        mock_proc.return_value = {"ok": True}
        store = MagicMock()
        store._conn.return_value.__enter__.return_value.execute = MagicMock()
        backfill_all(store, pdb, {}, user_id=42)
        # ensure_ticker_session was called with user_id=42
        kwargs = mock_sess.call_args.kwargs
        assert kwargs.get("user_id") == 42
        # process_analysis was called with user_id=42
        assert mock_proc.call_args.kwargs.get("user_id") == 42
