"""Dashboard's ``alerts_count`` must scope to the requesting user.

Bug fixed: ``api_dashboard`` previously called ``list_alerts()`` with no
user_id, so the count tile showed the system-wide active alerts —
revealing that other users existed and how many alerts they had.
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase


def test_dashboard_alerts_count_only_self(alice_client, bob_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id

    db.add_alert("AAPL", "price_above", 200.0, user_id=alice_id)
    db.add_alert("MSFT", "price_below", 300.0, user_id=alice_id)
    db.add_alert("TSLA", "price_above", 250.0, user_id=bob_id)

    bob_body = bob_client.get("/api/dashboard").get_json()
    assert bob_body["alerts_count"] == 1

    alice_body = alice_client.get("/api/dashboard").get_json()
    assert alice_body["alerts_count"] == 2
