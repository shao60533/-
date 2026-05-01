"""/api/portfolio/transactions field contract for the React island.

Frozen contract:
    * ``action`` is uppercase ``BUY`` / ``SELL`` (frontend matches the
      literal upper-case string for color)
    * ``timestamp`` is canonical YYYY-MM-DD HH:MM:SS
    * ``date`` is the legacy alias of ``timestamp`` (both fields point at
      the same value so old clients keep rendering the time column)
"""

from __future__ import annotations

from stock_trading_system.portfolio.manager import PortfolioManager


def _pm(app_client) -> PortfolioManager:
    return PortfolioManager(app_client["db_path"])


def test_transactions_returns_uppercase_action(alice_client, app_client):
    pm = _pm(app_client)
    alice_id = app_client["users"].alice.id
    pm.add_position("AAPL", 1, 150, user_id=alice_id)
    body = alice_client.get("/api/portfolio/transactions").get_json()
    assert body
    assert body[0]["action"] == "BUY"


def test_transactions_returns_timestamp_field(alice_client, app_client):
    pm = _pm(app_client)
    alice_id = app_client["users"].alice.id
    pm.add_position("AAPL", 1, 150, user_id=alice_id)
    body = alice_client.get("/api/portfolio/transactions").get_json()
    assert body[0].get("timestamp")


def test_transactions_includes_date_alias_for_legacy(alice_client, app_client):
    pm = _pm(app_client)
    alice_id = app_client["users"].alice.id
    pm.add_position("AAPL", 1, 150, user_id=alice_id)
    body = alice_client.get("/api/portfolio/transactions").get_json()
    assert body[0].get("date") == body[0].get("timestamp")
