"""F1 tests: plan content fingerprint dedup."""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.migrations.paper_trade_v1_3 import migrate, _compute_fingerprint


@pytest.fixture()
def db_path(tmp_path):
    """Create a DB with paper_trade tables + run v1.3 migration."""
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE paper_trade_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
            start_capital REAL NOT NULL, start_date TEXT NOT NULL,
            config_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO paper_trade_sessions VALUES (1, 'AAPL', 'live', 'running', 100000, '2026-01-01', '{}', '2026-01-01');

        CREATE TABLE paper_trade_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL, analysis_id INTEGER NOT NULL,
            rating TEXT, thesis TEXT,
            holding_months_min INTEGER, holding_months_max INTEGER,
            raw_summary TEXT, plan_json TEXT NOT NULL, parse_method TEXT,
            status TEXT DEFAULT 'active', superseded_by_plan_id INTEGER,
            superseded_at TEXT, created_at TEXT NOT NULL
        );

        CREATE TABLE paper_trade_planned_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
            order_type TEXT NOT NULL, sequence INTEGER NOT NULL,
            pct_target_total REAL, trigger_kind TEXT NOT NULL,
            trigger_json TEXT NOT NULL, status TEXT DEFAULT 'pending',
            triggered_date TEXT, triggered_price REAL, trade_id INTEGER,
            description TEXT, superseded_by_plan_id INTEGER,
            superseded_at TEXT, created_at TEXT NOT NULL
        );

        CREATE TABLE analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, date TEXT, signal TEXT,
            trade_decision TEXT, created_at TEXT
        );
    """)
    conn.commit()
    conn.close()

    # Run migration to add F1 columns
    migrate(path, dry_run=False)
    return path


class TestMigration:
    def test_idempotent(self, db_path):
        result = migrate(db_path, dry_run=False)
        assert result["status"] == "already_migrated"

    def test_dry_run(self, tmp_path):
        path = str(tmp_path / "dry.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE paper_trade_plans (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE analysis_history (id INTEGER PRIMARY KEY)")
        conn.close()
        result = migrate(path, dry_run=True)
        assert result["status"] == "dry_run"

    def test_backup_created(self, tmp_path):
        path = str(tmp_path / "bak.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE paper_trade_plans (id INTEGER PRIMARY KEY, plan_json TEXT)")
        conn.execute("CREATE TABLE analysis_history (id INTEGER PRIMARY KEY)")
        conn.close()
        migrate(path)
        assert (tmp_path / "bak.db.pre-v1_3.bak").exists()


class TestFingerprint:
    def test_same_plan_same_fp(self):
        plan = {"entry_low": 100, "stop_loss": 90, "orders": [{"sequence": 1, "trigger": {"kind": "immediate"}, "pct_target_total": 0.5}]}
        assert _compute_fingerprint(plan) == _compute_fingerprint(plan)

    def test_different_plan_different_fp(self):
        p1 = {"entry_low": 100, "stop_loss": 90, "orders": []}
        p2 = {"entry_low": 110, "stop_loss": 90, "orders": []}
        assert _compute_fingerprint(p1) != _compute_fingerprint(p2)

    def test_order_independent(self):
        """Order of fields in dict should not affect fingerprint."""
        p1 = {"entry_low": 100, "stop_loss": 90}
        p2 = {"stop_loss": 90, "entry_low": 100}
        assert _compute_fingerprint(p1) == _compute_fingerprint(p2)


class TestSavePlanDedup:
    def test_same_plan_twice_reconfirms(self, db_path):
        from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore
        store = PaperTradeStore(db_path)
        plan = {"entry_low": 100, "entry_high": 110, "stop_loss": 90, "orders": []}

        id1 = store.save_plan(session_id=1, analysis_id=10, rating="BUY", thesis="test",
                               holding_months=None, raw_summary=None, plan=plan, parse_method="llm")
        id2 = store.save_plan(session_id=1, analysis_id=11, rating="BUY", thesis="test",
                               holding_months=None, raw_summary=None, plan=plan, parse_method="llm")
        assert id1 == id2  # same plan_id returned (dedup)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT reconfirmed_count, analysis_ids FROM paper_trade_plans WHERE id=?", (id1,)).fetchone()
        conn.close()
        assert row[0] == 2  # reconfirmed_count incremented

    def test_different_plan_creates_new(self, db_path):
        from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore
        store = PaperTradeStore(db_path)
        plan1 = {"entry_low": 100, "stop_loss": 90, "orders": []}
        plan2 = {"entry_low": 120, "stop_loss": 100, "orders": []}

        id1 = store.save_plan(session_id=1, analysis_id=10, rating="BUY", thesis="a",
                               holding_months=None, raw_summary=None, plan=plan1, parse_method="llm")
        id2 = store.save_plan(session_id=1, analysis_id=11, rating="BUY", thesis="b",
                               holding_months=None, raw_summary=None, plan=plan2, parse_method="llm")
        assert id1 != id2  # different plan

    def test_concurrent_safe(self, db_path):
        """Multiple threads saving same plan should not create duplicates."""
        import threading
        from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore
        store = PaperTradeStore(db_path)
        plan = {"entry_low": 200, "stop_loss": 180, "orders": []}
        ids = []

        def _save(aid):
            pid = store.save_plan(session_id=1, analysis_id=aid, rating="BUY", thesis="t",
                                   holding_months=None, raw_summary=None, plan=plan, parse_method="llm")
            ids.append(pid)

        threads = [threading.Thread(target=_save, args=(100 + i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should return same plan_id (dedup)
        assert len(set(ids)) == 1
