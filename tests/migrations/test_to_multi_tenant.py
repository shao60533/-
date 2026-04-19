"""Tests for the multi-tenant migration script."""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.migrations.to_multi_tenant import migrate


def _create_legacy_db(path: str) -> None:
    """Create a minimal legacy single-user database."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE positions (
            ticker TEXT PRIMARY KEY,
            market TEXT NOT NULL,
            shares REAL NOT NULL,
            avg_cost REAL NOT NULL,
            added_date TEXT NOT NULL
        );
        INSERT INTO positions VALUES ('AAPL', 'us', 10, 150.0, '2026-01-01');
        INSERT INTO positions VALUES ('MSFT', 'us', 5, 300.0, '2026-01-02');

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, action TEXT, shares REAL, price REAL,
            timestamp TEXT, notes TEXT
        );
        INSERT INTO transactions (ticker, action, shares, price, timestamp)
        VALUES ('AAPL', 'BUY', 10, 150.0, '2026-01-01 10:00:00');

        CREATE TABLE daily_snapshots (
            date TEXT PRIMARY KEY,
            total_value REAL, total_cost REAL, pnl REAL,
            pnl_pct REAL, positions_json TEXT
        );

        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, condition TEXT, threshold REAL,
            created TEXT, triggered INTEGER DEFAULT 0
        );
        INSERT INTO alerts (ticker, condition, threshold, created)
        VALUES ('AAPL', 'price_above', 200.0, '2026-01-01');

        CREATE TABLE paper_trade_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, mode TEXT NOT NULL,
            status TEXT NOT NULL, start_capital REAL NOT NULL,
            start_date TEXT NOT NULL, config_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            type TEXT, params_json TEXT, title TEXT,
            status TEXT, created_by TEXT DEFAULT 'user',
            created_at TEXT
        );
        INSERT INTO tasks VALUES ('t1', 'analysis', '{}', 'test', 'success', 'user', '2026-01-01');
    """)
    conn.commit()
    conn.close()


class TestMigrationIdempotent:
    """Migration is idempotent — running twice does not fail."""

    def test_first_run_succeeds(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        result = migrate(db, admin_email="admin@test.com", admin_password="TestPass123!")
        assert result["status"] == "success"
        assert result["admin_email"] == "admin@test.com"

    def test_second_run_is_noop(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@test.com", admin_password="P@ss1234")
        result = migrate(db, admin_email="admin@test.com", admin_password="P@ss1234")
        assert result["status"] == "already_migrated"


class TestMigrationBackup:
    """Backup file is created before migration."""

    def test_backup_created(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")
        assert (tmp_path / "portfolio.db.pre-mt.bak").exists()


class TestMigrationDryRun:
    """Dry-run prints SQL but doesn't modify the database."""

    def test_dry_run_no_changes(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        result = migrate(db, admin_email="admin@local", dry_run=True)
        assert result["status"] == "dry_run"

        conn = sqlite3.connect(db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "users" not in tables


class TestMigrationTables:
    """New tables are created correctly."""

    def test_users_table_created(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        admin = conn.execute("SELECT * FROM users WHERE email='admin@local'").fetchone()
        conn.close()
        assert admin is not None

    def test_invite_codes_table_created(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        conn.execute("SELECT * FROM invite_codes").fetchall()
        conn.close()

    def test_user_settings_table_created(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        conn.execute("SELECT * FROM user_settings").fetchall()
        conn.close()

    def test_analysis_bookmarks_table_created(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        conn.execute("SELECT * FROM analysis_bookmarks").fetchall()
        conn.close()


class TestMigrationUserIdColumn:
    """Private tables get user_id column with admin as default."""

    def test_positions_has_user_id(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT ticker, user_id FROM positions").fetchall()
        conn.close()
        assert len(rows) == 2
        assert all(r[1] is not None for r in rows)

    def test_no_null_user_ids(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        for table in ["positions", "transactions", "alerts"]:
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"
            ).fetchone()[0]
            assert null_count == 0, f"{table} has NULL user_id rows"
        conn.close()


class TestMigrationTasksCreatedBy:
    """tasks.created_by is migrated from string to FK."""

    def test_tasks_created_by_migrated(self, tmp_path):
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="P@ss1234")

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT created_by FROM tasks WHERE id='t1'").fetchone()
        conn.close()
        assert row[0] is not None
        assert isinstance(row[0], int)


class TestMigrationBcrypt:
    """Admin password is hashed with bcrypt rounds>=12."""

    def test_admin_password_bcrypt(self, tmp_path):
        import bcrypt
        db = str(tmp_path / "portfolio.db")
        _create_legacy_db(db)
        migrate(db, admin_email="admin@local", admin_password="SecurePass1!")

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT password_hash FROM users WHERE email='admin@local'").fetchone()
        conn.close()
        hashed = row[0]
        assert hashed.startswith("$2b$12$")
        assert bcrypt.checkpw(b"SecurePass1!", hashed.encode())
