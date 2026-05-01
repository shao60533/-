"""/api/search must scope private tables to the requesting user.

Bug fixed here: pre-fix, ``api_search`` called ``db.get_all_positions()``,
``db.get_transactions()``, and ``db.get_active_alerts()`` with no
user_id, so any user typing a substring of another user's ticker would
see that other user's row leak into the typeahead results. Notes were
also indexed, exposing private free-text via casual substring queries.
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.models import Position, Transaction


def test_search_positions_isolated(alice_client, bob_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    db.upsert_position(Position(
        ticker="AAPL", market="us", shares=10, avg_cost=150.0,
        added_date="2026-04-01", user_id=alice_id,
    ))
    resp = bob_client.get("/api/search?q=AAPL")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["positions"] == [], (
        "bob must not see alice's AAPL position via search"
    )


def test_search_alerts_isolated(alice_client, bob_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    db.add_alert("AAPL", "price_above", 200.0, user_id=alice_id)
    resp = bob_client.get("/api/search?q=AAPL")
    body = resp.get_json()
    assert body["alerts"] == [], (
        "bob must not see alice's alerts via search"
    )


def test_search_transactions_notes_not_indexed(alice_client, app_client):
    """Even within a user's own results, private notes must not be the
    haystack for substring matching — otherwise a casual coworker
    looking over a shoulder could fish out trade thesis text."""
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    db.add_transaction(Transaction(
        id=None, ticker="AAPL", action="buy", shares=10, price=150.0,
        timestamp="2026-04-01 10:00", notes="secret-alpha-thesis",
        user_id=alice_id,
    ))
    resp = alice_client.get("/api/search?q=secret-alpha")
    body = resp.get_json()
    assert body["transactions"] == [], (
        "notes must not be indexed by /api/search"
    )


def test_search_transactions_isolated(alice_client, bob_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    db.add_transaction(Transaction(
        id=None, ticker="AAPL", action="buy", shares=10, price=150.0,
        timestamp="2026-04-01 10:00", notes="",
        user_id=alice_id,
    ))
    resp = bob_client.get("/api/search?q=AAPL")
    body = resp.get_json()
    assert body["transactions"] == []
