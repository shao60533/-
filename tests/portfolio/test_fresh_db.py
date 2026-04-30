"""Fresh-DB smoke tests for the multi-tenant portfolio schema.

The bug these tests pin: prior to this fix, ``PortfolioDatabase._init_tables``
created the four private tables (positions/transactions/daily_snapshots/
alerts) without ``user_id`` columns. A fresh DB then crashed with
``OperationalError: no column user_id`` the first time
``PortfolioManager.add_position`` tried to write.

These tests run against a brand-new SQLite file and assert that the four
critical write paths (add/sell/snapshot/alert) work end-to-end without
needing any post-hoc ``to_multi_tenant`` migration.
"""

from __future__ import annotations

from stock_trading_system.alerts.monitor import AlertMonitor
from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.manager import PortfolioManager


def test_fresh_db_add_position_works(tmp_path):
    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)  # bootstrap
    pm = PortfolioManager(db_path)
    pm.add_position("AAPL", 10, 150.0, user_id=1)
    rows = pm.get_holdings(user_id=1)
    assert any(r["ticker"] == "AAPL" for r in rows)


def test_fresh_db_sell_position_works(tmp_path):
    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)
    pm = PortfolioManager(db_path)
    pm.add_position("AAPL", 10, 150.0, user_id=1)
    pm.sell_position("AAPL", 10, 160.0, user_id=1)
    rows = pm.get_holdings(user_id=1)
    assert not any(r["ticker"] == "AAPL" for r in rows)


def test_fresh_db_take_snapshot_works(tmp_path):
    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)
    pm = PortfolioManager(db_path)
    pm.add_position("AAPL", 5, 100.0, user_id=1)
    pm.take_snapshot(user_id=1)
    snaps = PortfolioDatabase(db_path).get_snapshots(user_id=1, days=30)
    assert len(snaps) >= 1


def test_fresh_db_add_alert_works(tmp_path):
    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)
    monitor = AlertMonitor({"portfolio": {"db_path": db_path}})
    monitor.add_alert("AAPL", "price_above", 200.0, user_id=1)
    alerts = monitor.list_alerts(user_id=1, scope="user")
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "AAPL"
    assert alerts[0]["user_id"] == 1


def test_fresh_db_two_users_isolated(tmp_path):
    """Two users adding the same ticker do not collide on the legacy
    single-tenant ticker PK; each gets their own row."""
    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)
    pm = PortfolioManager(db_path)
    pm.add_position("AAPL", 10, 150.0, user_id=1)
    pm.add_position("AAPL", 5, 200.0, user_id=2)

    db = PortfolioDatabase(db_path)
    p1 = db.get_position("AAPL", user_id=1)
    p2 = db.get_position("AAPL", user_id=2)
    assert p1 is not None and p1.shares == 10 and p1.avg_cost == 150.0
    assert p2 is not None and p2.shares == 5 and p2.avg_cost == 200.0
