"""PaperTradeStore self-initialization includes v1.3 F1 dedup columns.

Before this fix, ``_SCHEMA_TRADING_PLANS`` was missing fingerprint /
reconfirmed_count / reconfirmed_at / analysis_ids, but ``save_plan`` wrote
to those columns — a fresh DB created via ``PaperTradeStore(db_path)``
would crash on the very first plan save unless the standalone
``paper_trade_v1_3`` migration was also run. These tests pin the new
behaviour so the regression doesn't return.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore


F1_PLAN_COLS = {
    "fingerprint",
    "reconfirmed_count",
    "reconfirmed_at",
    "analysis_ids",
}


def test_fresh_db_save_plan_works_without_migration(tmp_path):
    """A brand-new DB must support save_plan without paper_trade_v1_3."""
    p = str(tmp_path / "fresh.db")
    store = PaperTradeStore(p)
    with sqlite3.connect(p) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(paper_trade_plans)")}
    assert F1_PLAN_COLS.issubset(cols)

    sid = store.create_ticker_session(
        ticker="AAPL", start_date="2026-04-15",
        start_capital=10_000.0,
    )
    plan_id = store.save_plan(
        session_id=sid, analysis_id=1, rating="A", thesis="t",
        holding_months=(1, 6), raw_summary="r",
        plan={"orders": [], "rating": "A", "thesis": "t"},
        parse_method="regex",
    )
    assert plan_id > 0


def test_existing_db_idempotent_migration(tmp_path):
    """Pre-v1.3 DB without the 4 new cols must auto-upgrade on init."""
    p = str(tmp_path / "old.db")
    with sqlite3.connect(p) as c:
        c.executescript("""
            CREATE TABLE paper_trade_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                task_id TEXT, start_capital REAL NOT NULL, start_date TEXT NOT NULL,
                end_date TEXT, config_json TEXT NOT NULL,
                auto_track INTEGER DEFAULT 0, is_system INTEGER DEFAULT 0,
                ticker TEXT, last_eod_date TEXT,
                metrics_json TEXT, benchmark_metrics_json TEXT,
                created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE TABLE paper_trade_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                analysis_id INTEGER NOT NULL,
                rating TEXT, thesis TEXT,
                holding_months_min INTEGER, holding_months_max INTEGER,
                raw_summary TEXT, plan_json TEXT NOT NULL,
                parse_method TEXT, status TEXT DEFAULT 'active',
                superseded_by_plan_id INTEGER, superseded_at TEXT,
                created_at TEXT NOT NULL
            );
        """)
    PaperTradeStore(p)  # init triggers idempotent ALTER
    with sqlite3.connect(p) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(paper_trade_plans)")}
        sess_cols = {r[1]
                     for r in c.execute("PRAGMA table_info(paper_trade_sessions)")}
    assert F1_PLAN_COLS.issubset(cols)
    # session-level v1.3 columns also added on the existing DB.
    assert "user_id" in sess_cols
    assert "replay_mode" in sess_cols


def test_fresh_db_create_session_with_user_id(tmp_path):
    """create_ticker_session writes user_id when given."""
    p = str(tmp_path / "user.db")
    store = PaperTradeStore(p)
    sid = store.create_ticker_session(
        ticker="MSFT", start_date="2026-04-15",
        start_capital=10_000.0, user_id=42,
    )
    sess = store.find_session_by_ticker("MSFT", user_id=42)
    assert sess is not None
    assert int(sess["id"]) == sid
    # Sanity: a different user does not match.
    assert store.find_session_by_ticker("MSFT", user_id=99) is None
