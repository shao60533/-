"""hardening-iteration-v1 P1.3 — PortfolioManager._user_id() raises.

Pre-P1.3 the manager fell through to ``return None`` when called outside
a Flask request and without explicit user_id, which let DB layers below
write/read in "no tenant filter" mode. P1.3 makes that path raise so
worker/cron/CLI callers can't silently leak across tenants.

Also covers P1.6: TaskManager.submit raises when created_by can't be
resolved (was: fell back to the literal string ``"user"``, which broke
the tasks.created_by INTEGER contract).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Empty portfolio.db with the minimum schema PortfolioManager touches."""
    db_path = tmp_path / "portfolio.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ticker TEXT, market TEXT,
            shares REAL, avg_cost REAL, added_date TEXT,
            UNIQUE(user_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ticker TEXT, action TEXT,
            shares REAL, price REAL,
            timestamp TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            user_id INTEGER, date TEXT,
            total_value REAL, total_cost REAL,
            pnl REAL, pnl_pct REAL,
            positions_json TEXT,
            PRIMARY KEY (user_id, date)
        );
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)


# ── _user_id() contract ────────────────────────────────────────────────────


def test_user_id_raises_outside_flask_and_no_param(tmp_db):
    """Worker/CLI context = no Flask request, no g.user → must raise."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    with pytest.raises(RuntimeError, match="missing tenant context"):
        pm._user_id()


def test_user_id_returns_explicit_param(tmp_db):
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    assert pm._user_id(user_id=42) == 42


def test_get_holdings_raises_when_no_tenant_context(tmp_db):
    """All public methods that depend on _user_id() inherit the raise."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    with pytest.raises(RuntimeError, match="missing tenant context"):
        pm.get_holdings()


def test_add_position_raises_when_no_tenant_context(tmp_db):
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    with pytest.raises(RuntimeError, match="missing tenant context"):
        pm.add_position("AAPL", 100, 150.0)


def test_add_position_works_with_explicit_user_id(tmp_db):
    """Explicit user_id is the proper escape hatch for worker/CLI callers."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    pm.add_position("AAPL", 100, 150.0, user_id=7)
    # Roundtrip check — the row landed under user_id=7, not NULL.
    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT user_id FROM positions WHERE ticker = ?", ("AAPL",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 7


def test_take_snapshot_raises_when_no_tenant_context(tmp_db):
    from stock_trading_system.portfolio.manager import PortfolioManager
    pm = PortfolioManager(tmp_db)
    with pytest.raises(RuntimeError, match="missing tenant context"):
        pm.take_snapshot()


# ── TaskManager.submit created_by (P1.6) ───────────────────────────────────


def test_task_manager_submit_raises_without_created_by(tmp_path):
    """P1.6: cron/CLI submit path must pass created_by explicitly."""
    from stock_trading_system.tasks.task_store import TaskStore
    from stock_trading_system.tasks.task_manager import TaskManager

    db_path = str(tmp_path / "tasks.db")
    store = TaskStore(db_path)
    tm = TaskManager(store=store)
    # Register a no-op worker so the task type itself isn't the blocker.
    tm.register("noop", lambda params, cb: {"ok": True})

    with pytest.raises(RuntimeError, match="created_by missing"):
        tm.submit("noop", {})


def test_task_manager_submit_accepts_explicit_created_by(tmp_path):
    from stock_trading_system.tasks.task_store import TaskStore
    from stock_trading_system.tasks.task_manager import TaskManager

    db_path = str(tmp_path / "tasks.db")
    store = TaskStore(db_path)
    tm = TaskManager(store=store)
    tm.register("noop", lambda params, cb: {"ok": True})

    task = tm.submit("noop", {}, created_by=99)
    # task_store stores created_by as TEXT (SQLite is loose-typed); the
    # important contract is that the field exists and equals 99 numerically.
    assert int(task["created_by"]) == 99
    tm.shutdown(wait=True, cancel_futures=True)
