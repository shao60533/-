"""v1.2: ``/api/screen/v3/results/<id>`` surfaces a ``run_metadata``
block + projects per-candidate roundtable into a top-level envelope so
the React island can render the run banner + Top 5 grid without
re-walking candidates."""

from __future__ import annotations

import sqlite3


def _seed_screen_v3_task(app_client, *, owner_id: int, payload: dict,
                          submit_params: dict | None = None) -> str:
    """Create a ``screen_v3`` task + persist its result; return task id."""
    from stock_trading_system.web import app as app_module

    db_path = app_client["db_path"]
    with app_client["app"].test_request_context():
        tm = app_module._get_task_manager()
    task = tm.submit(
        task_type="screen_v3",
        params=submit_params or {"market": "us", "candidate_n": 20,
                                  "gurus": ["buffett", "lynch"]},
        title="v3 metadata test",
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


# ── run_metadata ─────────────────────────────────────────────────────────


def test_results_returns_run_metadata(alice_client, app_client):
    """v1.4 contract: legacy payloads written by v1.0–v1.3 only carried
    ``{llm_calls, cache_hits}`` where ``llm_calls`` semantically meant
    ``total_units`` (it was set to ``len(units)``). The DTO must now
    backfill the new fields (``total_units``, ``new_llm_calls``,
    ``failed_units``) so the React banner can render truthful counts;
    ``cache_hit_pct`` denominator switches to ``total_units`` so the
    rate stays correct even when half the run was retry-failures.

    For this legacy fixture (80 total, 24 cached, 0 failed):
        new_llm_calls = 80 - 24 - 0 = 56
        total_units   = 80 (fallback from legacy llm_calls)
        cache_hit_pct = 24 / 80 * 100 = 30
    """
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={
            "candidates": [{
                "ticker": "AAPL", "signal": "bullish",
                "composite_score": 60.0, "guru_scores": {},
            }],
            "metrics": {"llm_calls": 80, "cache_hits": 24, "duration_sec": 138},
            "mode": "agent_rt",
            "gurus_used": ["buffett", "lynch", "munger", "graham"],
        },
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    md = body["run_metadata"]
    assert md["mode"] == "agent_rt"
    # Legacy llm_calls=80 → reinterpreted as total_units. The exposed
    # ``llm_calls`` is now an alias for ``new_llm_calls`` (56).
    assert md["total_units"] == 80
    assert md["new_llm_calls"] == 56
    assert md["llm_calls"] == 56  # alias matches new_llm_calls
    assert md["cache_hits"] == 24
    assert md["cache_hit_pct"] == 30  # 24 / 80 * 100
    assert md["failed_units"] == 0
    assert md["duration_sec"] == 138
    assert md["gurus_used"] == ["buffett", "lynch", "munger", "graham"]
    assert md["candidates_count"] == 1


def test_run_metadata_falls_back_to_selected_gurus(alice_client, app_client):
    """The pipeline emits ``selected_gurus``; the spec asks for
    ``gurus_used``. The DTO must accept either."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={
            "candidates": [],
            "metrics": {"llm_calls": 0},
            "mode": "agent",
            "selected_gurus": ["buffett"],
        },
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["run_metadata"]["gurus_used"] == ["buffett"]


def test_run_metadata_handles_zero_llm_calls_without_div_zero(alice_client, app_client):
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [], "metrics": {"llm_calls": 0, "cache_hits": 0}},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["run_metadata"]["cache_hit_pct"] == 0


def test_run_metadata_legacy_payload_returns_zeros(alice_client, app_client):
    """Pre-v1.2 payloads have no metrics/mode/gurus_used — DTO must
    surface zeros + empty list rather than crash. Task submit-params
    here also omit ``gurus`` so the fallback chain bottoms out at []."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{"ticker": "AAPL", "signal": "bullish",
                                  "composite_score": 50.0}]},
        submit_params={"market": "us", "candidate_n": 5},  # no gurus
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    md = body["run_metadata"]
    assert md["llm_calls"] == 0
    assert md["cache_hits"] == 0
    assert md["cache_hit_pct"] == 0
    assert md["gurus_used"] == []
    # Mode falls back to "agent" when no roundtable + no explicit mode.
    assert md["mode"] == "agent"
    assert md["roundtable_enabled"] is False


def test_run_metadata_mode_falls_back_to_task_params_mode(alice_client, app_client):
    """When the worker payload doesn't carry ``mode`` (legacy), pull from
    the submitted task's ``params_json``."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [], "metrics": {}},
        submit_params={"market": "us", "mode": "agent_rt",
                        "gurus": ["buffett"]},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["run_metadata"]["mode"] == "agent_rt"


# ── roundtable envelope ──────────────────────────────────────────────────


def test_roundtable_envelope_built_from_candidates(alice_client, app_client):
    """v1.2 default: each candidate carries its own roundtable dict.
    The DTO collects them into ``{items: [...]}`` so the React grid
    renders without re-walking candidates."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={
            "candidates": [
                {
                    "ticker": "AAPL", "signal": "split",
                    "composite_score": 75.0, "guru_scores": {},
                    "roundtable": {
                        "ticker": "AAPL",
                        "consensus": ["buffett", "lynch"],
                        "dissent": ["dalio"],
                        "split": True,
                        "debate_snippets": [
                            "🟢 buffett: long-term moat",
                            "🔴 dalio: macro headwind",
                            "⚖️ judge: contested",
                        ],
                    },
                },
                {
                    "ticker": "MSFT", "signal": "bullish",
                    "composite_score": 80.0, "guru_scores": {},
                    "roundtable": {
                        "ticker": "MSFT",
                        "consensus": ["buffett", "lynch", "dalio"],
                        "dissent": [],
                        "split": False,
                        "debate_snippets": ["🟢 buffett: AI tailwind"],
                    },
                },
            ],
            "metrics": {"llm_calls": 12, "cache_hits": 0},
            "mode": "agent_rt",
        },
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    rt = body["roundtable"]
    assert "items" in rt
    items = {it["ticker"]: it for it in rt["items"]}
    assert set(items.keys()) == {"AAPL", "MSFT"}
    assert items["AAPL"]["split"] is True
    assert items["AAPL"]["consensus"] == ["buffett", "lynch"]
    assert items["MSFT"]["split"] is False
    assert items["MSFT"]["debate_snippets"][0].startswith("🟢")
    # roundtable_enabled inferred from per-candidate dicts.
    assert body["run_metadata"]["roundtable_enabled"] is True


def test_roundtable_envelope_none_when_no_per_candidate(alice_client, app_client):
    """Agent (no roundtable) mode → no envelope, banner shows 无圆桌."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={"candidates": [{"ticker": "X", "signal": "bullish",
                                  "composite_score": 50}],
                  "metrics": {"llm_calls": 4}},
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["roundtable"] is None
    assert body["run_metadata"]["roundtable_enabled"] is False


def test_roundtable_envelope_preserves_explicit_legacy_shape(alice_client, app_client):
    """If the worker emitted a top-level envelope already (legacy
    summary text), the DTO leaves it as-is."""
    tid = _seed_screen_v3_task(
        app_client, owner_id=app_client["users"].alice.id,
        payload={
            "candidates": [{"ticker": "X", "signal": "bullish",
                              "composite_score": 50}],
            "roundtable": {"summary": "consensus reached", "consensus": "BUY"},
            "metrics": {"llm_calls": 4},
        },
    )
    body = alice_client.get(f"/api/screen/v3/results/{tid}").get_json()
    assert body["roundtable"]["summary"] == "consensus reached"
