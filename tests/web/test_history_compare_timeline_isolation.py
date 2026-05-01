"""compare / timeline DTOs must not leak per-user advice columns and
must overlay only the requesting user's own advice.

Pre-fix: ``PortfolioDatabase._STRUCTURED_COLS`` selected the per-user
advice columns (action / confidence / position_pct / entry_low /
entry_high / stop_loss / take_profit) directly off the shared row.
Anyone calling /api/history/compare?ids=... or /api/history/timeline/<ticker>
would see the original creator's holdings-aware plan.

Post-fix: the projection drops those columns and the API layer overlays
``my_advice`` from ``user_analysis_advice`` if (and only if) the
requesting user has their own row.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase


_LEAKY_KEYS = (
    "action", "confidence", "position_pct",
    "entry_low", "entry_high", "stop_loss", "take_profit",
    "advice_json",
)


def _seed_legacy_row_with_advice_columns(app_client, ticker="AAPL") -> int:
    """Inject a row that still carries advice in the structured columns
    (simulating an upstream / pre-migration row that escaped the strip pass)."""
    db_path = app_client["db_path"]
    db = PortfolioDatabase(db_path)
    aid = db.save_analysis({
        "ticker": ticker, "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """UPDATE analysis_history SET
                 advice_json = ?, action = ?, confidence = ?,
                 position_pct = ?, entry_low = ?, entry_high = ?,
                 stop_loss = ?, take_profit = ?
               WHERE id = ?""",
            ('{"action":"BUY"}', "BUY", "high",
             0.05, 145.0, 150.0, 140.0, 165.0, aid),
        )
    return aid


def test_compare_dto_strips_advice_columns(bob_client, app_client):
    aid = _seed_legacy_row_with_advice_columns(app_client)
    body = bob_client.get(f"/api/history/compare?ids={aid}").get_json()
    rec = body["records"][0]
    for key in _LEAKY_KEYS:
        assert key not in rec, (
            f"compare DTO leaked '{key}' (={rec.get(key)!r}); "
            f"per-user advice must not live on the shared row projection"
        )
    assert rec.get("my_advice") is None


def test_timeline_dto_strips_advice_columns(bob_client, app_client):
    _seed_legacy_row_with_advice_columns(app_client, ticker="AAPL")
    body = bob_client.get("/api/history/timeline/AAPL").get_json()
    assert body["records"], "timeline must return at least the seeded row"
    for rec in body["records"]:
        for key in _LEAKY_KEYS:
            assert key not in rec, (
                f"timeline DTO leaked '{key}' for non-creator user"
            )


def test_compare_dto_overlays_my_advice_for_owner(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = db.save_analysis({
        "ticker": "MSFT", "date": "2026-04-15", "signal": "BUY",
        "created_by": alice_id,
    })
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY", "stop_loss": 380.0,
                "entry_price_low": 395.0, "entry_price_high": 405.0,
                "suggested_position_pct": 0.04},
        holdings_snapshot="[]",
    )
    body = alice_client.get(f"/api/history/compare?ids={aid}").get_json()
    rec = body["records"][0]
    assert rec["my_advice"] is not None
    assert rec["my_advice"]["action"] == "BUY"
    assert rec["my_advice"]["stop_loss"] == 380.0


def test_compare_dto_does_not_overlay_others_advice(
    bob_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = db.save_analysis({
        "ticker": "TSLA", "date": "2026-04-15", "signal": "BUY",
        "created_by": alice_id,
    })
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY", "stop_loss": 200.0},
        holdings_snapshot="[]",
    )
    body = bob_client.get(f"/api/history/compare?ids={aid}").get_json()
    rec = body["records"][0]
    assert rec.get("my_advice") is None, (
        "bob must not inherit alice's user_analysis_advice via my_advice"
    )
