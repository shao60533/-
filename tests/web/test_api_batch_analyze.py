"""Tests for POST /api/batch/analyze — batch_analysis task entry point.

Pins the four contract guarantees that matter at the route boundary:
  1. anonymous → 401
  2. empty holdings → 400 reason="no_holdings"
  3. ≥1 holding → 200 + queued task with correct total_holdings + type
  4. cross-user isolation — bob cannot read alice's submitted task

The worker pipeline (workers.py::make_batch_analysis_worker) is NOT
exercised here — it owns its own test surface. We only check that the
route enqueues the right shape and that multi-tenant scoping holds.
"""

from __future__ import annotations

import pytest

from stock_trading_system.web import app as app_module


def _add_holding(client, ticker: str, shares: float, price: float) -> None:
    """Buy a position for the logged-in user via the public API."""
    resp = client.post(
        "/api/portfolio/add",
        json={"ticker": ticker, "shares": shares, "price": price},
    )
    assert resp.status_code == 200, resp.get_json()


# ── 1. Auth gate ─────────────────────────────────────────────────────────────


def test_anonymous_returns_401(app_client):
    anon = app_client["make_client"]()
    resp = anon.post("/api/batch/analyze")
    assert resp.status_code == 401
    assert (resp.get_json() or {}).get("error") == "unauthorized"


# ── 2. Empty-holdings preflight ──────────────────────────────────────────────


def test_no_holdings_returns_400_with_reason(alice_client):
    # alice fixture user has zero positions by default.
    resp = alice_client.post("/api/batch/analyze")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["reason"] == "no_holdings"
    assert "message" in body


# ── 3. Happy path — queue the task with correct envelope ─────────────────────


def test_submits_task_with_total_holdings_and_created_by(alice_client, app_client):
    # Add 3 holdings, then submit batch.
    _add_holding(alice_client, "AAPL", 10, 150.0)
    _add_holding(alice_client, "MSFT", 5, 320.0)
    _add_holding(alice_client, "GOOG", 2, 130.0)

    resp = alice_client.post(
        "/api/batch/analyze",
        json={"skip_recent_hours": 4},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "queued"
    assert body["total_holdings"] == 3
    task_id = body["task_id"]
    assert task_id

    # Verify the task hits the task manager with the right shape.
    # TaskManager normalises created_by to a string (legacy compat with
    # the pre-multi-tenant "user" sentinel); the SQL row stores it as
    # TEXT. Compare via str() rather than fighting the column type.
    tm = app_module._task_manager
    assert tm is not None, "task manager should be initialized after first submit"
    task = tm.get(task_id)
    assert task is not None
    assert task["type"] == "batch_analysis"
    assert str(task["created_by"]) == str(app_client["users"].alice.id)
    import json
    params = json.loads(task["params_json"]) if isinstance(task.get("params_json"), str) else task.get("params") or {}
    assert params.get("skip_recent_hours") == 4
    assert params.get("__user_id__") == app_client["users"].alice.id


# ── 4. Multi-tenant isolation ────────────────────────────────────────────────


def test_cross_user_task_isolation(alice_client, bob_client):
    # alice has holdings; bob does not.
    _add_holding(alice_client, "AAPL", 10, 150.0)

    alice_resp = alice_client.post(
        "/api/batch/analyze",
        json={"skip_recent_hours": 4},
    )
    assert alice_resp.status_code == 200, alice_resp.get_json()
    alice_task_id = alice_resp.get_json()["task_id"]

    # bob cannot read alice's task — multi-tenant middleware on
    # /api/tasks/<id> filters by created_by.
    bob_view = bob_client.get(f"/api/tasks/{alice_task_id}")
    assert bob_view.status_code in (403, 404), bob_view.get_json()
