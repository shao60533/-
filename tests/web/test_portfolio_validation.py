"""Validation guards on /api/portfolio/add and /api/portfolio/sell.

Bug fixed: pre-fix, both endpoints called ``float(data["shares"])`` and
``float(data["price"])`` directly with no positivity check, so a typo
or malicious client could record a BUY of -1 shares. Worse, sell with
no holding was logged as "no position found, recording transaction
only" — leaving an orphan SELL row dangling in transactions.
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.manager import PortfolioManager


def _db(app_client) -> PortfolioDatabase:
    return PortfolioDatabase(app_client["db_path"])


def _pm(app_client) -> PortfolioManager:
    return PortfolioManager(app_client["db_path"])


def test_buy_negative_shares_rejected(alice_client, app_client):
    resp = alice_client.post("/api/portfolio/add",
                              json={"ticker": "AAPL", "shares": -1, "price": 150})
    assert resp.status_code == 400
    db = _db(app_client)
    alice_id = app_client["users"].alice.id
    assert db.get_transactions(user_id=alice_id) == []


def test_buy_zero_price_rejected(alice_client):
    resp = alice_client.post("/api/portfolio/add",
                              json={"ticker": "AAPL", "shares": 1, "price": 0})
    assert resp.status_code == 400


def test_buy_missing_ticker_rejected(alice_client):
    resp = alice_client.post("/api/portfolio/add",
                              json={"shares": 1, "price": 150})
    assert resp.status_code == 400


def test_sell_no_holding_rejected(alice_client, app_client):
    resp = alice_client.post("/api/portfolio/sell",
                              json={"ticker": "AAPL", "shares": 1, "price": 150})
    assert resp.status_code == 400
    db = _db(app_client)
    alice_id = app_client["users"].alice.id
    assert db.get_transactions(user_id=alice_id) == []


def test_sell_excess_shares_rejected(alice_client, app_client):
    pm = _pm(app_client)
    alice_id = app_client["users"].alice.id
    pm.add_position("AAPL", 10, 150, user_id=alice_id)
    resp = alice_client.post("/api/portfolio/sell",
                              json={"ticker": "AAPL", "shares": 100, "price": 160})
    assert resp.status_code == 400
    db = _db(app_client)
    txns = db.get_transactions(user_id=alice_id)
    # Only the BUY from setup should remain; no orphan SELL row.
    assert all((t.action or "").upper() != "SELL" for t in txns)


def test_sell_valid_decrements_position(alice_client, app_client):
    pm = _pm(app_client)
    alice_id = app_client["users"].alice.id
    pm.add_position("AAPL", 10, 150, user_id=alice_id)
    resp = alice_client.post("/api/portfolio/sell",
                              json={"ticker": "AAPL", "shares": 5, "price": 160})
    assert resp.status_code == 200
    db = _db(app_client)
    pos = db.get_position("AAPL", user_id=alice_id)
    assert pos is not None
    assert abs(pos.shares - 5) < 1e-9
