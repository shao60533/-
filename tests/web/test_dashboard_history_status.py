"""/api/dashboard surfaces history_status / history_count so the
DashboardPage can render an "insufficient snapshots — click 重新计算"
notice instead of a flat 1-point line.

Bug pre-v1.16: the response only carried ``history``; the React
island had no way to tell "user has no holdings yet" apart from
"user has holdings but daily_snapshots only has 1 row" — both
collapsed into the same flat-line UI.
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.models import (
    DailySnapshot, Position,
)


def _seed_position(db: PortfolioDatabase, user_id: int) -> None:
    db.upsert_position(Position(
        ticker="AAPL", market="us", shares=10, avg_cost=150.0,
        added_date="2026-04-01", user_id=user_id,
    ))


def _seed_snapshot(db: PortfolioDatabase, user_id: int, date: str,
                    total_value: float = 1500.0) -> None:
    db.save_snapshot(DailySnapshot(
        date=date,
        total_value=total_value, total_cost=1500.0,
        pnl=total_value - 1500.0,
        pnl_pct=(total_value - 1500.0) / 1500.0 * 100,
        positions_json="[]",
        user_id=user_id,
    ))


def test_dashboard_status_ok_with_multiple_snapshots(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    uid = app_client["users"].alice.id
    _seed_position(db, uid)
    for d in ("2026-04-15", "2026-04-16", "2026-04-17"):
        _seed_snapshot(db, uid, d)
    body = alice_client.get("/api/dashboard?history_days=all").get_json()
    assert body["history_status"] == "ok"
    assert body["history_count"] == 3
    assert body["history_first_date"] == "2026-04-15"
    assert body["history_last_date"] == "2026-04-17"


def test_dashboard_status_insufficient_with_holdings_one_snapshot(
    alice_client, app_client,
):
    """Holdings exist but only 1 snapshot — the failure mode the
    user reported. Frontend renders the "click 重新计算" notice."""
    db = PortfolioDatabase(app_client["db_path"])
    uid = app_client["users"].alice.id
    _seed_position(db, uid)
    _seed_snapshot(db, uid, "2026-04-15")
    body = alice_client.get("/api/dashboard?history_days=all").get_json()
    assert body["history_status"] == "insufficient_snapshots"
    assert body["history_count"] == 1


def test_dashboard_status_insufficient_with_holdings_no_snapshots(
    alice_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    _seed_position(db, app_client["users"].alice.id)
    body = alice_client.get("/api/dashboard?history_days=all").get_json()
    assert body["history_status"] == "insufficient_snapshots"
    assert body["history_count"] == 0
    assert body["history_first_date"] is None


def test_dashboard_status_ok_with_no_holdings(alice_client):
    """User has no positions at all → not 'insufficient', just 'ok'
    (an empty curve isn't a problem to flag)."""
    body = alice_client.get("/api/dashboard?history_days=all").get_json()
    assert body["history_status"] == "ok"
    assert body["history_count"] == 0


def test_dashboard_status_filters_to_user(alice_client, bob_client, app_client):
    """Bob's snapshot count must not bleed into Alice's response."""
    db = PortfolioDatabase(app_client["db_path"])
    bob_id = app_client["users"].bob.id
    _seed_position(db, bob_id)
    for d in ("2026-04-15", "2026-04-16"):
        _seed_snapshot(db, bob_id, d)
    # Alice has nothing — must report 0.
    body = alice_client.get("/api/dashboard?history_days=all").get_json()
    assert body["history_count"] == 0
    # Bob sees his own.
    bob_body = bob_client.get("/api/dashboard?history_days=all").get_json()
    assert bob_body["history_count"] == 2
    assert bob_body["history_status"] == "ok"
