"""v1.7 backtest + reports contract regression.

Locks the post-cleanup contracts so a future tweak that brings back
either drift (``strategy`` vs ``strategy_id``, ``rsi_reversal`` vs
``rsi_mean_reversion``, ``label`` vs ``name``, ``report_type`` vs
``type``, or shared-vs-private routing for reports) is caught at CI
time rather than by a user reporting "回测又跳到 buy_and_hold 了".
"""

from __future__ import annotations

import json

import pytest


# ── /api/backtest/strategies — single registry, canonical shape ────────


def test_strategies_endpoint_returns_canonical_ids(alice_client):
    """v1.7 — the strategies endpoint serves ``BacktestEngine`` (the
    worker engine), not the parallel ``Backtester`` registry. Earlier
    versions had drift between the two: ``rsi_reversal`` vs
    ``rsi_mean_reversion`` and ``label`` vs ``name``. The frontend
    reads the engine list now so the dropdown ids match what the
    worker actually executes.
    """
    body = alice_client.get("/api/backtest/strategies").get_json()
    assert isinstance(body, dict) and "strategies" in body
    strategies = body["strategies"]
    ids = {s["id"] for s in strategies}
    # Canonical ids — the user-visible RSI strategy is named
    # ``rsi_mean_reversion``. The legacy ``rsi_reversal`` id MUST NOT
    # appear in the registry; it's only honored by ``canonical_strategy_id``
    # on the engine side as a one-release migration alias.
    assert "rsi_reversal" not in ids, \
        "legacy id leaked into the strategies endpoint"
    assert ids == {"sma_crossover", "rsi_mean_reversion", "buy_and_hold"}


def test_strategies_entries_have_both_name_and_label(alice_client):
    """Frontend reads ``s.name ?? s.label ?? s.id``. To make either
    consumer work during migration, every entry must expose both
    keys. The pre-fix world had ``Backtester`` returning ``label``
    while ``BacktestEngine`` returned ``name`` — the dropdown showed
    ``undefined`` for one of them depending on which API you hit."""
    body = alice_client.get("/api/backtest/strategies").get_json()
    for s in body["strategies"]:
        assert s.get("name"), f"strategy {s['id']} missing ``name``"
        assert s.get("label"), f"strategy {s['id']} missing ``label``"
        assert s["name"] == s["label"], (
            f"strategy {s['id']} ``name``/``label`` should match for now "
            f"(soft migration); got name={s['name']!r} label={s['label']!r}"
        )


# ── Reports privacy boundary ──────────────────────────────────────────


def test_report_task_is_private_other_user_403(
    alice_client, bob_client, app_client,
):
    """Daily/weekly/monthly reports render the user's holdings + PnL
    inline. Earlier the ``report`` type was in
    ``TaskStore.SHARED_TYPES`` so any logged-in user could read another
    user's report. Lock private semantics here: Bob must get 403 on
    Alice's report task detail."""
    # Alice submits a report task.
    res = alice_client.post(
        "/api/tasks/submit",
        json={"type": "report", "params": {"type": "daily"}},
    ).get_json()
    task_id = res.get("task_id") or res.get("id")
    assert task_id, f"submit response missing task_id: {res}"

    # Bob tries to read it — must be denied because reports are
    # private (carry per-user holdings).
    detail = bob_client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 403, (
        f"Bob should not see Alice's report task. Got {detail.status_code}: "
        f"{detail.get_json()}"
    )

    # And the result endpoint too — even after the task finishes, the
    # body must not be readable by another user.
    result = bob_client.get(f"/api/tasks/{task_id}/result")
    assert result.status_code == 403


def test_report_task_alice_can_read_own(alice_client):
    """The owner CAN of course read their own task. This guards
    against an over-eager privacy fix that locks the owner out too."""
    res = alice_client.post(
        "/api/tasks/submit",
        json={"type": "report", "params": {"type": "daily"}},
    ).get_json()
    task_id = res.get("task_id") or res.get("id")
    detail = alice_client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200


# ── Reports submission contract — params.type, not params.report_type ─


def test_report_submit_sends_type_field(alice_client, app_client):
    """The frontend now sends ``params.type`` (canonical) instead of
    ``params.report_type``. Verify the round-trip — the persisted
    params row carries ``type`` so a re-submit / retry works.
    """
    res = alice_client.post(
        "/api/tasks/submit",
        json={"type": "report", "params": {"type": "weekly"}},
    ).get_json()
    task_id = res.get("task_id") or res.get("id")
    assert task_id

    # Pull the task row and inspect the persisted params.
    body = alice_client.get(f"/api/tasks/{task_id}").get_json()
    params = json.loads(body.get("params_json") or "{}")
    assert params.get("type") == "weekly", (
        f"persisted params should carry the canonical 'type' key — "
        f"got {params}"
    )


# ── Backtest result endpoint — JSON columns unpacked ──────────────────


def test_task_result_endpoint_returns_unpacked_backtest_shape(
    alice_client, app_client,
):
    """After ``TaskStore.save_result`` writes to ``backtest_results``,
    the ``/api/tasks/<id>/result`` endpoint must return a body whose
    ``result.metrics`` / ``result.equity_curve`` / ``result.trades``
    are structured (parsed), not JSON strings. Earlier the row was
    returned with ``metrics_json`` as a literal string and the React
    detail page rendered an empty stat row.

    This test seeds the row directly — the worker isn't run because
    we don't want to depend on yfinance / a router fixture for a
    contract assertion.
    """
    import sqlite3
    from stock_trading_system.tasks.task_store import TaskStore, hash_params, now_iso

    store = TaskStore(app_client["db_path"])
    users = app_client["users"]

    task_id = "test-bt-task-123"
    params = {"ticker": "AAPL", "strategy_id": "sma_crossover"}
    store.insert({
        "id": task_id, "type": "backtest", "title": "test",
        "params_json": json.dumps(params),
        "status": "success",
        "params_hash": hash_params("backtest", params),
        "created_by": users.alice.id,
    })
    result_payload = {
        "ticker": "AAPL",
        "strategy_id": "sma_crossover",
        "period": "2025-01-01~2025-06-01",
        "initial_capital": 100_000,
        "metrics": {
            "final_value": 112000, "total_return": 0.12,
            "annualized_return": 0.24, "max_drawdown": -0.08,
            "win_rate": 0.6, "num_trades": 5, "sharpe_ratio": 1.3,
        },
        "equity_curve": [
            {"date": "2025-01-02", "value": 100000},
            {"date": "2025-01-03", "value": 100500},
        ],
        "trades": [{"date": "2025-01-15", "action": "BUY",
                     "price": 150.0, "shares": 10, "pnl": 0}],
    }
    ref = store.save_result("backtest", task_id, result_payload)
    # Wire result_ref + status onto the task row so the API thinks
    # it's complete.
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE tasks SET result_ref = ?, status = 'success' WHERE id = ?",
            (ref, task_id),
        )

    body = alice_client.get(f"/api/tasks/{task_id}/result").get_json()
    assert "result" in body, body
    r = body["result"]
    # Each of these would be a JSON string under the pre-v1.7
    # ``load_result`` (no unpacking).
    assert isinstance(r["metrics"], dict), \
        f"metrics must be parsed dict, got {type(r['metrics']).__name__}"
    assert r["metrics"]["sharpe_ratio"] == 1.3
    assert isinstance(r["equity_curve"], list)
    assert r["equity_curve"][0]["value"] == 100000
    assert isinstance(r["trades"], list)
    assert r["trades"][0]["action"] == "BUY"
    # Top-level metric lift — frontend reads ``result.total_return``.
    assert r["total_return"] == 0.12
    assert r["num_trades"] == 5
    # strategy_id round-trips intact (drives the ticker badge in the UI).
    assert r["strategy_id"] == "sma_crossover"


def test_task_result_endpoint_404_when_not_success(alice_client, app_client):
    """If the task isn't ``success`` yet, the result endpoint returns
    404 with a status message in the body — that's how the React
    detail page knows to keep polling rather than render a blank
    state. We don't care about the exact non-success status here
    (the cluster has different conventions for orphan tracking); we
    only care that the route surfaces a polling-friendly 404 with a
    machine-readable status field."""
    from stock_trading_system.tasks.task_store import TaskStore, hash_params

    store = TaskStore(app_client["db_path"])
    users = app_client["users"]

    task_id = "test-bt-not-ready-456"
    store.insert({
        "id": task_id, "type": "backtest", "title": "test",
        "params_json": json.dumps({"ticker": "AAPL"}),
        "status": "pending",
        "params_hash": hash_params("backtest", {"ticker": "AAPL"}),
        "created_by": users.alice.id,
    })
    resp = alice_client.get(f"/api/tasks/{task_id}/result")
    assert resp.status_code == 404, (
        f"Result endpoint must 404 while task isn't ready (got "
        f"{resp.status_code}: {resp.get_json()})"
    )
    body = resp.get_json()
    # Body must carry the ``status`` field so the React poller can
    # distinguish "still running" from "result corrupt".
    assert "status" in body, body
    assert body["status"] != "success"
