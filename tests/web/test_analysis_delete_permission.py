"""DELETE /api/history/<id> permission gate.

Shared analyses are research artefacts the whole org can read. Only the
original creator (or admin) may delete one — anyone else gets 403.
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase


def _seed(app_client, *, created_by: int, ticker="AAPL") -> int:
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-15", "signal": "BUY",
        "created_by": created_by,
    })


def test_non_creator_cannot_delete(alice_client, bob_client, app_client):
    aid = _seed(app_client, created_by=app_client["users"].alice.id)
    resp = bob_client.delete(f"/api/history/{aid}")
    assert resp.status_code == 403
    # And the row is still there
    db = PortfolioDatabase(app_client["db_path"])
    assert db.get_analysis_by_id(aid) is not None


def test_creator_can_delete_own(alice_client, app_client):
    aid = _seed(app_client, created_by=app_client["users"].alice.id)
    resp = alice_client.delete(f"/api/history/{aid}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("ok")
    db = PortfolioDatabase(app_client["db_path"])
    assert db.get_analysis_by_id(aid) is None


def test_admin_can_delete_any(admin_client, app_client):
    aid = _seed(app_client, created_by=app_client["users"].alice.id)
    resp = admin_client.delete(f"/api/history/{aid}")
    assert resp.status_code == 200
    db = PortfolioDatabase(app_client["db_path"])
    assert db.get_analysis_by_id(aid) is None


def test_unauthenticated_returns_401(anon_client, app_client):
    aid = _seed(app_client, created_by=app_client["users"].alice.id)
    resp = anon_client.delete(f"/api/history/{aid}")
    assert resp.status_code == 401


def test_delete_missing_row_returns_404_or_403(alice_client):
    """An id that does not exist must not allow deletion. Either 404
    (not found) or 403 (legacy row with no creator) is acceptable; the
    invariant is "no successful 200 OK"."""
    resp = alice_client.delete("/api/history/9999999")
    assert resp.status_code in (403, 404)
