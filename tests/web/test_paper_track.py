"""End-to-end tests for /api/paper/track.

The endpoint must:
  * read the requesting user's per-user advice (NOT shared advice_json),
  * create / reuse a per-user paper-trade session,
  * surface plan_id / num_orders / triggered to the UI, and
  * not leak Alice's advice into Bob's plan.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase


def _seed_analysis(db: PortfolioDatabase, *,
                    ticker: str = "AAPL",
                    date: str = "2026-04-15",
                    signal: str = "BUY",
                    advice_json: str = "",
                    created_by: int | None = None) -> int:
    return db.save_analysis({
        "ticker": ticker, "date": date, "signal": signal,
        "advice_json": advice_json, "created_by": created_by,
    })


def test_paper_track_returns_plan_id(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = _seed_analysis(db, created_by=alice_id)
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY",
                "entry_price_low": 145, "entry_price_high": 150,
                "stop_loss": 140, "suggested_position_pct": 0.05},
        holdings_snapshot="[]",
    )
    resp = alice_client.post("/api/paper/track", json={"analysis_id": aid})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    # plan_id may be falsy when advice is empty, but session must exist
    # and the surface fields must be present.
    assert body["session_id"] is not None
    assert "plan_id" in body
    assert "num_orders" in body
    assert "triggered" in body


def test_paper_track_creates_user_scoped_session(
    alice_client, bob_client, app_client,
):
    """Bob hitting /api/paper/track on Alice's analysis must not borrow
    Alice's session — Bob gets his own session row scoped to his user_id.
    """
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id
    aid = _seed_analysis(db, created_by=alice_id)
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY",
                "entry_price_low": 145, "entry_price_high": 150,
                "stop_loss": 140, "suggested_position_pct": 0.05},
        holdings_snapshot="[]",
    )

    alice_resp = alice_client.post("/api/paper/track", json={"analysis_id": aid})
    bob_resp = bob_client.post("/api/paper/track", json={"analysis_id": aid})
    assert alice_resp.status_code == 200
    assert bob_resp.status_code == 200
    alice_sid = alice_resp.get_json()["session_id"]
    bob_sid = bob_resp.get_json()["session_id"]
    assert alice_sid != bob_sid, "sessions must be user-scoped"

    with sqlite3.connect(app_client["db_path"]) as c:
        c.row_factory = sqlite3.Row
        a_row = c.execute(
            "SELECT user_id FROM paper_trade_sessions WHERE id = ?",
            (alice_sid,),
        ).fetchone()
        b_row = c.execute(
            "SELECT user_id FROM paper_trade_sessions WHERE id = ?",
            (bob_sid,),
        ).fetchone()
    assert int(a_row["user_id"]) == int(alice_id)
    assert int(b_row["user_id"]) == int(bob_id)


def test_paper_track_does_not_leak_alice_advice_to_bob(
    alice_client, bob_client, app_client,
):
    """If only Alice has user_advice, Bob's plan must not contain Alice's numbers."""
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = _seed_analysis(db, created_by=alice_id)
    db.save_user_advice(
        user_id=alice_id, analysis_id=aid,
        advice={"action": "BUY", "stop_loss": 999.0,
                "entry_price_low": 999.0, "entry_price_high": 999.0,
                "suggested_position_pct": 0.99},
        holdings_snapshot="[]",
    )
    bob_resp = bob_client.post("/api/paper/track", json={"analysis_id": aid})
    assert bob_resp.status_code == 200
    body = bob_resp.get_json()
    assert body["ok"] is True
    # Plan json (if any) must NOT contain Alice's leaked 999 numbers.
    plan_id = body.get("plan_id")
    if plan_id:
        with sqlite3.connect(app_client["db_path"]) as c:
            row = c.execute(
                "SELECT plan_json FROM paper_trade_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        assert row is not None
        assert "999" not in (row[0] or "")


def test_paper_track_requires_login(anon_client):
    resp = anon_client.post("/api/paper/track", json={"analysis_id": 1})
    assert resp.status_code == 401


def test_paper_track_validates_analysis_id(alice_client):
    resp = alice_client.post("/api/paper/track", json={})
    assert resp.status_code == 400
    resp2 = alice_client.post(
        "/api/paper/track", json={"analysis_id": "not-an-int"},
    )
    assert resp2.status_code == 400


def test_paper_track_404_when_analysis_missing(alice_client):
    resp = alice_client.post("/api/paper/track", json={"analysis_id": 999_999})
    assert resp.status_code == 404
