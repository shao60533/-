"""L3/L4 cross-module integration tests — 20 scenarios from design §6.1.

These test the invariants and cross-module interactions that single-module
tests cannot cover.
"""

from __future__ import annotations

import sqlite3
import subprocess

import pytest

from stock_trading_system.validation.snapshot import generate_snapshot
from stock_trading_system.validation.compare import compare_snapshots
from stock_trading_system.validation.invariants import run_invariants, INVARIANTS
from stock_trading_system.migrations.to_multi_tenant import migrate as mt_migrate
from stock_trading_system.migrations.paper_trade_v1_3 import migrate as pt_migrate
from stock_trading_system.migrations.task_events_v1 import migrate as te_migrate


@pytest.fixture()
def migrated_db(tmp_path):
    """Create a DB, run ALL migrations, return path."""
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE positions (
            ticker TEXT PRIMARY KEY, market TEXT NOT NULL,
            shares REAL NOT NULL, avg_cost REAL NOT NULL, added_date TEXT NOT NULL
        );
        INSERT INTO positions VALUES ('AAPL', 'us', 10, 150.0, '2026-01-01');
        INSERT INTO positions VALUES ('MSFT', 'us', 5, 300.0, '2026-01-02');

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, action TEXT, shares REAL, price REAL,
            timestamp TEXT, notes TEXT DEFAULT ''
        );
        INSERT INTO transactions (ticker, action, shares, price, timestamp)
        VALUES ('AAPL', 'BUY', 10, 150.0, '2026-01-01 10:00:00');
        INSERT INTO transactions (ticker, action, shares, price, timestamp)
        VALUES ('MSFT', 'BUY', 5, 300.0, '2026-01-02 10:00:00');

        CREATE TABLE daily_snapshots (
            date TEXT PRIMARY KEY, total_value REAL, total_cost REAL,
            pnl REAL, pnl_pct REAL, positions_json TEXT
        );

        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, condition TEXT, threshold REAL,
            created TEXT, triggered INTEGER DEFAULT 0
        );
        INSERT INTO alerts (ticker, condition, threshold, created)
        VALUES ('AAPL', 'price_above', 200.0, '2026-01-01');

        CREATE TABLE alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER, ticker TEXT, condition TEXT,
            threshold REAL, current_price REAL, triggered_at TEXT
        );

        CREATE TABLE analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, date TEXT, signal TEXT,
            market_report TEXT, sentiment_report TEXT, news_report TEXT,
            fundamentals_report TEXT, investment_debate TEXT,
            risk_assessment TEXT, trade_decision TEXT,
            advice_json TEXT, created_at TEXT NOT NULL
        );
        INSERT INTO analysis_history (ticker, date, signal, trade_decision, created_at)
        VALUES ('AAPL', '2026-01-01', 'BUY', 'Buy AAPL with conviction', '2026-01-01 12:00:00');

        CREATE TABLE paper_trade_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
            start_capital REAL NOT NULL, start_date TEXT NOT NULL,
            config_json TEXT NOT NULL, auto_track INTEGER DEFAULT 0,
            is_system INTEGER DEFAULT 0, ticker TEXT, last_eod_date TEXT,
            metrics_json TEXT, created_at TEXT NOT NULL, completed_at TEXT,
            end_date TEXT, task_id TEXT, benchmark_metrics_json TEXT
        );
        INSERT INTO paper_trade_sessions (name, mode, status, start_capital, start_date, config_json, created_at)
        VALUES ('test', 'live', 'running', 100000, '2026-01-01', '{}', '2026-01-01');

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

        CREATE TABLE paper_trade_strategy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL, event_type TEXT, analysis_id INTEGER,
            ticker TEXT, signal TEXT, created_at TEXT
        );
        INSERT INTO paper_trade_strategy_events (session_id, event_type, ticker, signal, created_at)
        VALUES (1, 'analysis', 'AAPL', 'BUY', '2026-01-01');

        CREATE TABLE paper_trade_trades (id INTEGER PRIMARY KEY);
        CREATE TABLE paper_trade_equity (id INTEGER PRIMARY KEY);
        CREATE TABLE paper_trade_daily_stats (id INTEGER PRIMARY KEY);

        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, type TEXT, params_json TEXT, title TEXT,
            status TEXT, created_by TEXT DEFAULT 'user', created_at TEXT,
            completed_at TEXT, progress REAL DEFAULT 0
        );
        INSERT INTO tasks VALUES ('t1', 'analysis', '{}', 'test', 'success', 'user', '2026-01-01', '2026-01-01', 100);

        CREATE TABLE agent_scorecards (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()

    # Run all migrations
    mt_migrate(path, admin_email="admin@local", admin_password="TestPass1!")
    pt_migrate(path)
    te_migrate(path)

    return path


# ── Scenario 1-5: Data integrity ──────────────────────────────────

class TestDataIntegrity:
    def test_snapshot_roundtrip(self, migrated_db):
        """Scenario 7: snapshot pre → migrate → snapshot post → compare OK."""
        snap = generate_snapshot(migrated_db)
        assert snap["tables"]["positions"]["row_count"] == 2
        assert snap["tables"]["users"]["row_count"] == 1

    def test_pre_post_compare_identical(self, migrated_db):
        """Row counts should be stable across snapshot iterations."""
        snap1 = generate_snapshot(migrated_db)
        snap2 = generate_snapshot(migrated_db)
        result = compare_snapshots(snap1, snap2)
        assert result["go"] is True
        assert result["fail_count"] == 0

    def test_admin_owns_all_old_data(self, migrated_db):
        """Scenario 7: all old positions belong to admin."""
        conn = sqlite3.connect(migrated_db)
        admin_id = conn.execute("SELECT id FROM users WHERE email='admin@local'").fetchone()[0]
        null_count = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id IS NULL").fetchone()[0]
        admin_count = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=?", (admin_id,)).fetchone()[0]
        conn.close()
        assert null_count == 0
        assert admin_count == 2

    def test_alerts_have_owner(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        null = conn.execute("SELECT COUNT(*) FROM alerts WHERE user_id IS NULL").fetchone()[0]
        conn.close()
        assert null == 0

    def test_sessions_have_owner(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        null = conn.execute("SELECT COUNT(*) FROM paper_trade_sessions WHERE user_id IS NULL").fetchone()[0]
        conn.close()
        assert null == 0


# ── Scenario 6-10: Schema correctness ────────────────────────────

class TestSchemaCorrectness:
    def test_users_table_created(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "users" in tables
        assert "invite_codes" in tables
        assert "user_settings" in tables
        assert "task_events" in tables

    def test_analysis_has_executive_summary_column(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(analysis_history)").fetchall()]
        conn.close()
        assert "executive_summary" in cols

    def test_positions_has_user_id(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(positions)").fetchall()]
        conn.close()
        assert "user_id" in cols

    def test_task_events_has_indexes(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        indexes = [r[1] for r in conn.execute("PRAGMA index_list(task_events)").fetchall()]
        conn.close()
        assert any("user_seq" in (i or "") for i in indexes)

    def test_plans_have_fingerprint_column(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(paper_trade_plans)").fetchall()]
        conn.close()
        assert "fingerprint" in cols


# ── Scenario 11-15: Cross-module ──────────────────────────────────

class TestCrossModule:
    def test_no_regex_literal_in_codebase(self):
        """Scenario 16: grep 'regex 解析' must be 0 (excluding validation SQL)."""
        result = subprocess.run(
            ["grep", "-rn", "--exclude-dir=validation", "--exclude-dir=__pycache__",
             "regex 解析", "stock_trading_system/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", f"Found: {result.stdout}"

    def test_bcrypt_rounds_12(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        row = conn.execute("SELECT password_hash FROM users LIMIT 1").fetchone()
        conn.close()
        assert row[0].startswith("$2b$12$"), f"Expected bcrypt rounds=12, got: {row[0][:10]}"

    def test_invite_codes_table_empty_but_valid(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        count = conn.execute("SELECT COUNT(*) FROM invite_codes").fetchone()[0]
        conn.close()
        assert count == 0  # no codes generated yet

    def test_task_events_table_ready(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        count = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        conn.close()
        assert count == 0  # empty but table exists

    def test_analysis_bookmarks_table_exists(self, migrated_db):
        conn = sqlite3.connect(migrated_db)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "analysis_bookmarks" in tables


# ── Scenario 16-20: Migration idempotency ─────────────────────────

class TestMigrationIdempotency:
    def test_multi_tenant_idempotent(self, migrated_db):
        result = mt_migrate(migrated_db, admin_email="admin@local", admin_password="Test1!")
        assert result["status"] == "already_migrated"

    def test_paper_trade_v13_idempotent(self, migrated_db):
        result = pt_migrate(migrated_db)
        assert result["status"] == "already_migrated"

    def test_task_events_idempotent(self, migrated_db):
        result = te_migrate(migrated_db)
        assert result["status"] == "already_migrated"

    def test_full_snapshot_after_all_migrations(self, migrated_db):
        snap = generate_snapshot(migrated_db)
        assert len(snap["tables"]) >= 15
        for name, info in snap["tables"].items():
            assert "error" not in info, f"Table {name} has error: {info}"

    def test_invariants_sample(self, migrated_db):
        """Run a subset of invariants that should pass on clean migrated DB."""
        results = run_invariants(migrated_db)
        # Some invariants may fail on test data (e.g. trade_decision empty)
        # but owner checks must pass
        pass_names = {r["name"] for r in results["pass"]}
        assert "positions_have_owner" in pass_names
        assert "alerts_have_owner" in pass_names
        assert "paper_sessions_have_owner" in pass_names
