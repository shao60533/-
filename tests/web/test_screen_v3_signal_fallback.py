"""V3 result endpoint must backfill ``candidate.signal`` when the worker
emitted it as null. Production payload (task c49f5d09…) returned 20
candidates with ``signal: null`` and the dashboard showed 看多 0 / 看空 0
because the React island filtered on signal alone.
"""

from __future__ import annotations

import json
import sqlite3

import pytest


def _seed_screen_v3_task(app_client, *, owner_id: int, payload: dict) -> str:
    """Create a screen_v3 task + persist a generic result, return task id."""
    from stock_trading_system.web import app as app_module
    db_path = app_client["db_path"]
    with app_client["app"].test_request_context():
        tm = app_module._get_task_manager()
    task = tm.submit(
        task_type="screen_v3",
        params={"market": "us", "candidate_n": 20, "gurus": ["buffett"]},
        title="screen_v3 test",
        created_by=owner_id,
    )
    tid = task["id"]
    try:
        tm.cancel(tid)
    except Exception:
        pass

    store = (
        app_module._task_store
        if app_module._task_store is not None
        else app_module._get_task_store()
    )
    if store is None:
        with app_client["app"].test_request_context():
            store = app_module._get_task_store()
    ref = store.save_result(
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


# ── Tier 1: existing signal preserved ─────────────────────────────────────


def test_existing_signal_preserved(alice_client, app_client):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{
            "ticker": "AAPL", "signal": "bullish",
            "composite_score": 80.0, "guru_scores": {},
        }]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["candidates"][0]["signal"] == "bullish"


# ── Tier 2: derive from guru votes when signal is null ───────────────────


def test_signal_derived_from_guru_majority_bullish(alice_client, app_client):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{
            "ticker": "AAPL", "signal": None, "composite_score": 50.0,
            "guru_signals": [
                {"guru": "buffett", "signal": "bullish", "confidence": 0.9},
                {"guru": "graham",  "signal": "bullish", "confidence": 0.8},
                {"guru": "munger",  "signal": "bearish", "confidence": 0.6},
            ],
        }]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["candidates"][0]["signal"] == "bullish"


def test_signal_derived_from_guru_majority_bearish(alice_client, app_client):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{
            "ticker": "ZZZ", "signal": None, "composite_score": 80.0,
            "guru_signals": [
                {"guru": "buffett", "signal": "bearish", "confidence": 0.9},
                {"guru": "graham",  "signal": "bearish", "confidence": 0.8},
                {"guru": "munger",  "signal": "bullish", "confidence": 0.6},
            ],
        }]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    # bearish wins despite high composite_score (gurus take priority).
    assert body["candidates"][0]["signal"] == "bearish"


# ── Tier 3: composite_score band when no guru votes ──────────────────────


@pytest.mark.parametrize("score,expected", [
    (90.0, "bullish"),
    (65.0, "bullish"),
    (50.0, "neutral"),
    (40.0, "bearish"),
    (10.0, "bearish"),
])
def test_signal_derived_from_composite_score(alice_client, app_client, score, expected):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{
            "ticker": "T", "signal": None,
            "composite_score": score, "guru_scores": {},
        }]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["candidates"][0]["signal"] == expected


# ── Tier 4: never null, always a string ──────────────────────────────────


def test_signal_never_null_in_response(alice_client, app_client):
    """Production failure mode: 20 candidates with signal=null → counters
    show 0/0. The endpoint must always emit a non-empty string."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [
            {"ticker": "A", "signal": None, "composite_score": None},
            {"ticker": "B", "signal": "", "composite_score": 75.0},
            {"ticker": "C", "signal": None, "final_score": 30.0},
        ]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    sigs = [c["signal"] for c in body["candidates"]]
    assert all(isinstance(s, str) and s for s in sigs)
    # Spot-check: B (score=75) → bullish; C (score=30) → bearish.
    by_t = {c["ticker"]: c["signal"] for c in body["candidates"]}
    assert by_t["B"] == "bullish"
    assert by_t["C"] == "bearish"


def test_legacy_results_key_with_null_signals(alice_client, app_client):
    """Worker wrote ``results`` (legacy key) AND signal=null. Endpoint
    normalises both: renames to candidates AND derives signal."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"results": [{
            "ticker": "MSFT", "final_score": 72.0,
            "signal": None,
            "guru_signals": [
                {"guru": "buffett", "signal": "bullish", "confidence": 0.85},
            ],
        }]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert cand["composite_score"] == 72.0
    assert cand["signal"] == "bullish"
