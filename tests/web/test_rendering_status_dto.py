"""v1.7 — ``/api/history/<id>`` exposes the rendering state machine.

Covers the contract the React detail page reads to decide whether to
show the structured cards as primary or to surface the retry banner.
"""

from __future__ import annotations

import json
import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase


def _seed(app_client, *, rendering_json="", status="pending",
          error=None, signal_value="Buy"):
    """Insert one analysis_history row + return its id."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15",
        "signal": signal_value,
        "market_report": "## Market\n看多趋势确认。",
        "trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**",
        "created_by": app_client["users"].alice.id,
    })
    # Patch rendering fields directly — save_analysis only sets the
    # default ``pending`` status; we want explicit fixtures here.
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            """UPDATE analysis_history
                  SET rendering_json = ?, rendering_status = ?,
                      rendering_error = ?
                WHERE id = ?""",
            (rendering_json, status, error, aid),
        )
    return aid


def test_history_dto_surfaces_status_for_failed_extraction(alice_client, app_client):
    aid = _seed(app_client, status="failed",
                error="all 8 tabs failed extraction")
    body = alice_client.get(f"/api/history/{aid}").get_json()

    assert body["rendering_status"] == "failed"
    assert body["rendering_error"] == "all 8 tabs failed extraction"
    assert body["rendering_available_tabs"] == []
    # ``rendering`` itself is the parsed dict — empty when status is
    # failed and json is empty. UI uses ``rendering_status`` to pick
    # the banner; ``rendering`` to pick the cards.
    assert body["rendering"] == {}


def test_history_dto_surfaces_partial_with_available_tabs(alice_client, app_client):
    rendering = {
        "summary": {"rating": "Buy", "confidence": "high",
                    "action_direction": "ok", "key_metrics": [],
                    "decision_drivers": [], "one_line_takeaway": "x"},
        "Market": {"trend": "bullish", "summary": "ok"},
        "Sentiment": None, "News": None, "Fundamentals": None,
        "Investment Debate": None, "Risk Assessment": None, "Decision": None,
    }
    aid = _seed(
        app_client,
        rendering_json=json.dumps(rendering, ensure_ascii=False),
        status="partial",
        error="missing tabs: Sentiment, News, Fundamentals, Investment Debate, Risk Assessment, Decision",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["rendering_status"] == "partial"
    # Available list only includes tabs whose extraction is non-empty.
    assert body["rendering_available_tabs"] == ["summary", "Market"]
    assert body["rendering_error"] and "missing tabs" in body["rendering_error"]
    # Cards still ship for the tabs that succeeded.
    assert body["rendering"]["summary"]["rating"] == "Buy"


def test_history_dto_legacy_row_without_status_column_classified_as_empty(
    alice_client, app_client,
):
    """v1.6 rows have NULL ``rendering_status`` (column was added in
    v1.7 migration). The DTO falls back to ``_infer_rendering_status_legacy``
    so the React frontend doesn't render an undefined banner."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "OLD", "date": "2026-01-01",
        "signal": "Hold",
        "created_by": app_client["users"].alice.id,
    })
    # Wipe both ``rendering_json`` and the new status column to mimic
    # a row written before v1.7 ran.
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = NULL, "
            "rendering_status = NULL WHERE id = ?", (aid,),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["rendering_status"] == "empty"
    assert body["rendering_available_tabs"] == []


def test_history_dto_success_shows_no_error(alice_client, app_client):
    rendering = {k: {"x": 1} for k in (
        "summary", "Market", "Sentiment", "News", "Fundamentals",
        "Investment Debate", "Risk Assessment", "Decision",
    )}
    aid = _seed(
        app_client,
        rendering_json=json.dumps(rendering, ensure_ascii=False),
        status="success",
    )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["rendering_status"] == "success"
    assert body["rendering_error"] is None
    assert len(body["rendering_available_tabs"]) == 8


def test_rendering_retry_endpoint_enqueues_backfill_task(alice_client, app_client):
    """POST /api/history/<id>/rendering/retry must return a task_id
    referring to an ``analysis_rendering_backfill`` row in tasks."""
    aid = _seed(app_client, status="failed", error="LLM timeout")
    resp = alice_client.post(f"/api/history/{aid}/rendering/retry", json={})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ok"] is True
    assert body["analysis_id"] == aid
    task_id = body.get("task_id") or body.get("id")
    assert task_id

    # Confirm the task row carries the right type + analysis_id param.
    task_body = alice_client.get(f"/api/tasks/{task_id}").get_json()
    assert task_body["type"] == "analysis_rendering_backfill"
    params = json.loads(task_body.get("params_json") or "{}")
    assert params.get("analysis_id") == aid


def test_rendering_retry_404_for_unknown_analysis(alice_client):
    resp = alice_client.post("/api/history/999999/rendering/retry", json={})
    assert resp.status_code == 404
