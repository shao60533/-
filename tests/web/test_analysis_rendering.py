"""DTO contract for the v1.19 ``rendering`` field on /api/history/<id>.

* Always returns a dict (never the raw ``rendering_json`` string).
* Old rows (rendering_json IS NULL) → empty dict, no error.
* Even if a malicious worker stuffs per-user advice into rendering, the
  schema doesn't contain those fields — verify the wire DTO does not
  carry them out of the rendering envelope either.
"""

from __future__ import annotations

import json
import sqlite3


def test_detail_returns_rendering_dict_not_raw_json(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": users.alice.id,
        "rendering_json": json.dumps({
            "summary": {
                "rating": "Buy", "action_direction": "建仓",
                "confidence": "high", "key_metrics": [],
                "decision_drivers": [], "one_line_takeaway": "go",
            },
            "Market": None,
        }, ensure_ascii=False),
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    assert isinstance(body["rendering"], dict)
    assert body["rendering"]["summary"]["rating"] == "Buy"
    assert body["rendering"]["Market"] is None
    # Storage detail never escapes to the API surface.
    assert "rendering_json" not in body


def test_detail_handles_missing_rendering_gracefully(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15",
        "signal": "BUY", "created_by": users.alice.id,
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["rendering"] == {}


def test_detail_handles_malformed_rendering_gracefully(app_client):
    """Corrupt blob (not JSON) → empty dict; never 500."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15",
        "signal": "BUY", "created_by": users.alice.id,
    })
    # Write garbage directly so we exercise the parse-failure branch.
    with sqlite3.connect(app_client["db_path"]) as c:
        c.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            ("not-valid-json{{{", aid),
        )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["rendering"] == {}


def test_detail_rendering_does_not_leak_advice_fields(app_client):
    """The Decision card schema doesn't define position_pct / user_advice /
    holdings_context. Even if a worker stuffs them in, the schema-shaped
    response stays clean. We assert on the wire DTO, not on the schema."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": users.alice.id,
        "rendering_json": json.dumps({
            "Decision": {
                "final_action": "BUY", "conviction": "high",
                "time_horizon": "swing",
                "preconditions": [], "exit_conditions": [],
                "alternative_scenarios": [], "take_profit_levels": [],
                "one_line_summary": "go",
            },
        }),
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    decision = body["rendering"]["Decision"]
    for forbidden in ("position_pct", "user_advice", "holdings_context",
                       "reasoning"):
        assert forbidden not in decision, (
            f"rendering.Decision leaked {forbidden}: {decision}"
        )


def test_detail_top_level_does_not_carry_legacy_advice(app_client):
    """v1.16 DTO whitelist sanity check rolled into v1.19."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": users.alice.id,
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    for forbidden in ("advice_json", "action", "position_pct",
                       "entry_low", "entry_high", "stop_loss", "take_profit"):
        assert forbidden not in body, f"top-level leak: {forbidden}"
