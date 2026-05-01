"""/api/screen/v3/results normalisation + params privacy.

Bug fixed: workers across versions wrote candidates under different keys
(``candidates`` vs ``results``) and used ``final_score`` /
``guru_signals`` instead of the React island's ``composite_score`` /
``guru_scores``. The endpoint now normalises both shapes.

Privacy bug: the response previously embedded the full ``params`` dict
verbatim, which contains ``user_id`` / ``provider`` and other internals.
Non-owner viewers now see only the ``screen_v3`` whitelist.
"""

from __future__ import annotations

import json
import sqlite3

import pytest


def _seed_screen_v3_task(app_client, *, owner_id: int,
                          payload: dict, params: dict | None = None) -> str:
    """Create a screen_v3 task row + persist a generic result payload,
    return the task id for the route to follow."""
    db_path = app_client["db_path"]
    # Submit a blank task via TaskManager so all the bookkeeping is real.
    from stock_trading_system.web import app as app_module
    with app_client["app"].test_request_context():
        tm = app_module._get_task_manager()
    task = tm.submit(
        task_type="screen_v3",
        params=params or {"market": "us", "candidate_n": 20,
                          "gurus": ["buffett"], "user_id": owner_id,
                          "provider": "qwen"},
        title="screen_v3 test",
        created_by=owner_id,
    )
    tid = task["id"]

    # Cancel to keep the worker from actually running while we poke at
    # the row.
    try:
        tm.cancel(tid)
    except Exception:
        pass

    # Use TaskStore.save_result to ensure task_results_generic exists
    # (the table is created lazily on first write).
    store = app_module._get_task_store() if app_module._task_store is None else app_module._task_store
    if store is None:
        with app_client["app"].test_request_context():
            store = app_module._get_task_store()
    ref = store.save_result(
        # Use a non-routed task_type so save_result falls into the
        # generic JSON-blob path that mirrors how screen_v3 actually
        # persists results today.
        task_type="screen_v3_test_generic",
        task_id=tid,
        result=payload,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE tasks SET result_ref = ?, status = 'completed', "
            "completed_at = datetime('now') WHERE id = ?",
            (ref, tid),
        )
    return tid


# ── Schema normalisation ─────────────────────────────────────────────────


def test_results_endpoint_normalizes_results_to_candidates(
    alice_client, app_client,
):
    """Worker wrote ``results`` (legacy key); endpoint maps to candidates."""
    legacy_payload = {
        "results": [
            {
                "ticker": "AAPL",
                "final_score": 87.5,
                "signal": "bullish",
                "guru_signals": [
                    {"guru": "buffett", "signal": "bullish",
                     "confidence": 0.9, "reasoning": "moat"},
                    {"guru": "graham", "signal": "neutral",
                     "confidence": 0.6, "reasoning": "fair"},
                ],
            },
        ],
    }
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload=legacy_payload,
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["ticker"] == "AAPL"
    assert cand["composite_score"] == 87.5
    assert "guru_scores" in cand
    assert cand["guru_scores"]["buffett"]["confidence"] == 0.9
    assert cand["guru_scores"]["graham"]["signal"] == "neutral"


def test_results_endpoint_keeps_canonical_shape(alice_client, app_client):
    """When the worker already emits canonical shape, pass through unchanged."""
    canonical = {
        "candidates": [
            {
                "ticker": "MSFT",
                "composite_score": 90.0,
                "signal": "bullish",
                "guru_scores": {
                    "munger": {"signal": "bullish", "confidence": 0.85},
                },
            },
        ],
    }
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload=canonical,
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["composite_score"] == 90.0
    assert body["candidates"][0]["guru_scores"]["munger"]["confidence"] == 0.85


def test_results_endpoint_empty_payload_returns_empty_candidates(
    alice_client, app_client,
):
    """Worker wrote nothing → 200 with an empty candidates array."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"summary": "no winners"},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["candidates"] == []


# ── Params privacy ───────────────────────────────────────────────────────


def test_results_strips_internal_params_for_non_owner(
    alice_client, bob_client, app_client,
):
    """Bob viewing Alice's shared screen_v3 result must not see user_id /
    provider on params."""
    tid = _seed_screen_v3_task(
        app_client,
        owner_id=app_client["users"].alice.id,
        payload={"candidates": []},
        params={
            "market": "us", "candidate_n": 20,
            "gurus": ["buffett"], "mode": "agent",
            "with_roundtable": False,
            "nl_query": "AI 龙头",
            "user_id": app_client["users"].alice.id,
            "provider": "qwen",
            "__user_id__": app_client["users"].alice.id,
        },
    )
    body = bob_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert "params" in body
    p = body["params"]
    for forbidden in ("user_id", "provider", "__user_id__"):
        assert forbidden not in p, f"params leaked '{forbidden}' to non-owner"
    # Whitelisted keys are still surfaced.
    assert p.get("market") == "us"
    assert p.get("gurus") == ["buffett"]


def test_results_owner_sees_full_params(alice_client, app_client):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": []},
        params={"market": "us", "candidate_n": 20,
                "gurus": ["buffett"],
                "user_id": app_client["users"].alice.id,
                "provider": "qwen"},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    # Owner CAN see her own internal context — the privacy rule only
    # gates *cross-user* leaks.
    assert body["params"].get("provider") == "qwen"
