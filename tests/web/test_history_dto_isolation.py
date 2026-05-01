"""Whitelist + advice-leak regressions for /api/history and /api/history/<id>.

Two layers of protection:

1. ``task_store._save_analysis_result`` MUST drop any ``advice`` field on the
   worker result so the shared ``analysis_history`` row never carries it.
2. ``/api/history`` and ``/api/history/<id>`` MUST emit a whitelisted DTO so
   even if a legacy row had ``advice_json`` populated, a non-creator reader
   never sees it at the top level or inside ``advice``.
"""

from __future__ import annotations

import json
import sqlite3

from stock_trading_system.tasks.task_store import TaskStore


# ── 1. task_store back-door is closed ────────────────────────────────────────


def test_save_analysis_result_drops_advice(tmp_path):
    """Even when the worker result carries advice/action/etc, the shared row
    persists ``advice_json=""`` and per-user advice columns NULL.
    """
    store = TaskStore(str(tmp_path / "tasks.db"))
    ref = store.save_result("analysis", "task-1", {
        "ticker": "AAPL", "date": "2026-04-30", "signal": "BUY",
        "market_report": "shared market notes",
        "trade_decision": "go long",
        # Adversarial: legacy worker still attaches per-user advice
        "advice": {
            "action": "BUY", "confidence": "high",
            "suggested_position_pct": 25.0,
            "entry_price_low": 150.0, "entry_price_high": 152.0,
            "stop_loss": 145.0, "take_profit": 170.0,
            "reasoning": "leak-attempt",
        },
        "created_by": 7, "provider": "qwen", "model": "qwen-plus",
        "config_hash": "deadbeef",
    })
    assert ref.startswith("analysis_history:")
    rid = int(ref.split(":", 1)[1])

    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT advice_json, action, confidence, position_pct, "
            "entry_low, entry_high, stop_loss, take_profit "
            "FROM analysis_history WHERE id = ?",
            (rid,),
        ).fetchone()

    assert row is not None
    assert row["advice_json"] == ""
    for col in ("action", "confidence", "position_pct",
                "entry_low", "entry_high", "stop_loss", "take_profit"):
        assert row[col] is None, f"{col} should be NULL on shared row"


# ── 2. /api/history list DTO never carries advice ────────────────────────────


def test_history_list_dto_never_exposes_advice(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-30", "signal": "BUY",
        "market_report": "shared", "trade_decision": "go long",
        # Force-populate the legacy column to simulate a pre-v1.14 row.
        "advice_json": json.dumps({
            "action": "BUY", "stop_loss": 145, "entry_price_low": 150,
            "reasoning": "alice's plan",
        }),
        "created_by": users.alice.id,
    })

    for client in (alice, bob):
        rv = client.get(f"/api/history?limit=5")
        assert rv.status_code == 200
        body = rv.get_json()
        for item in body.get("items", []):
            for forbidden in ("advice_json", "action", "position_pct",
                               "entry_low", "entry_high",
                               "stop_loss", "take_profit"):
                assert forbidden not in item, (
                    f"DTO leaked {forbidden} in /api/history; item={item}"
                )
            # The DTO does carry an `id` so the UI can link to detail.
            assert "id" in item
            assert "ticker" in item


# ── 3. /api/history/<id> detail DTO never leaks across users ─────────────────


def test_history_detail_dto_no_top_level_advice(app_client):
    users = app_client["users"]
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    # Pre-v1.14 row: legacy advice_json populated by Alice (the creator).
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-30", "signal": "BUY",
        "market_report": "shared", "trade_decision": "long",
        "advice_json": json.dumps({
            "action": "SELL", "stop_loss": 999.0,
            "entry_price_low": 999.0, "reasoning": "alice-only",
        }),
        "created_by": users.alice.id,
    })

    rv = bob.get(f"/api/history/{aid}")
    assert rv.status_code == 200
    body = rv.get_json()
    # Top-level: never any of the per-user advice fields.
    for forbidden in ("advice_json", "action", "position_pct",
                       "entry_low", "entry_high", "stop_loss", "take_profit"):
        assert forbidden not in body, (
            f"detail DTO leaked top-level {forbidden}; body keys={sorted(body)}"
        )
    # ``advice`` must be empty/None for Bob — he never saved his own row.
    assert body["advice"] in (None, {})
    # Smoke-check: shared body still renders.
    assert body["ticker"] == "AAPL"
    assert body["market_report"] == "shared"


def test_history_detail_creator_reads_own_user_advice(app_client):
    """Post-v1.16, even the creator must use the supported pattern —
    save_analysis writes the shared row, save_user_advice persists the
    holdings-aware private payload. The detail DTO surfaces only the
    requesting user's own advice, never the shared advice_json column.
    """
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-30", "signal": "BUY",
        "created_by": users.alice.id,
    })
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={"action": "BUY", "reasoning": "alice-private"},
        holdings_snapshot="[]",
    )

    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["advice"]["action"] == "BUY"
    assert body["advice"]["reasoning"] == "alice-private"
    # And still no top-level leak.
    assert "advice_json" not in body
    assert "action" not in body
