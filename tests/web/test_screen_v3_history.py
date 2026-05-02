"""/api/screen/v3/history — paginated multi-tenant view of past v3 runs.

Spec sourced from v1.24 (3-entry surface for screener V3). Tests
exercise:

    1. Multi-tenant guard — bob never sees alice's tasks (R-fix-12 边界)
    2. Summary aggregation — payload → candidates_count / avg_score /
       votes / consensus_rate_pct / top3_tickers / roundtable_enabled /
       llm_calls / cache_hit_pct / duration_sec
    3. Filter by mode + market (in-memory after SQL pulls success rows)
    4. Pagination — limit/offset + total
    5. Single-row prefill endpoint
    6. Cross-user single-row read returns 404
    7. Default response excludes pending/running tasks
    8. /screener-v3/history Jinja shell renders
"""

from __future__ import annotations

import json

import pytest


# ── Fixtures: write directly to TaskStore so we can pin the status. ────


def _store(app_client):
    """Get the TaskStore singleton attached to the configured app db."""
    from stock_trading_system.web import app as app_module
    with app_client["app"].test_request_context():
        return app_module._get_task_store()


def _seed(store, *, task_id: str, owner: int, params: dict,
           status: str = "success",
           result_payload: dict | None = None) -> str:
    """Insert one screen_v3 task row + optional generic result payload.

    Returns the task id. Caller can then GET /api/screen/v3/history.
    """
    store.insert({
        "id": task_id,
        "type": "screen_v3",
        "title": params.get("nl_query") or "screen_v3 test",
        "params_json": json.dumps(params, ensure_ascii=False),
        "status": status,
        "created_by": str(owner),
    })
    if result_payload is not None:
        ref = store._save_generic_result(task_id, result_payload)
        store.update(task_id, result_ref=ref, completed_at="2026-05-02 09:00:00")
    return task_id


# ── 1. Multi-tenant guard ──────────────────────────────────────────────


def test_history_returns_only_self(alice_client, bob_client, app_client):
    s = _store(app_client)
    _seed(s, task_id="t-alice-1",
          owner=app_client["users"].alice.id,
          params={"market": "us", "gurus": ["buffett"], "mode": "agent",
                   "candidate_n": 10})
    body = bob_client.get("/api/screen/v3/history?include_failed=true").get_json()
    assert body["items"] == []
    assert body["total"] == 0
    # Sanity: alice still sees her own row.
    body_a = alice_client.get(
        "/api/screen/v3/history?include_failed=true",
    ).get_json()
    assert body_a["total"] == 1


# ── 2. Summary aggregation ─────────────────────────────────────────────


def test_history_summary_extracted_correctly(alice_client, app_client):
    s = _store(app_client)
    _seed(
        s, task_id="t-sum-1",
        owner=app_client["users"].alice.id,
        params={
            "nl_query": "存储龙头股", "market": "us", "candidate_n": 3,
            "gurus": ["buffett", "lynch"],
            "mode": "agent_rt", "with_roundtable": True,
        },
        result_payload={
            "candidates": [
                {"ticker": "MU", "final_score": 58.8,
                 "signal": "bullish", "consensus": "unanimous"},
                {"ticker": "WDC", "final_score": 49.1,
                 "signal": "bullish", "consensus": "majority"},
                {"ticker": "STX", "final_score": 42.0,
                 "signal": "bearish", "consensus": "split"},
            ],
            "metrics": {
                "llm_calls": 80, "cache_hits": 24, "duration_sec": 138,
            },
            "roundtable": {"MU": {
                "consensus": ["lynch"], "dissent": [], "split": False,
                "debate_snippets": [],
            }},
        },
    )
    body = alice_client.get("/api/screen/v3/history").get_json()
    assert body["total"] == 1
    summary = body["items"][0]["summary"]
    assert summary["candidates_count"] == 3
    # (58.8 + 49.1 + 42.0) / 3 = 49.97 → rounded to 1 decimal = 50.0
    assert summary["avg_score"] == 50.0
    assert summary["votes"] == {"bullish": 2, "bearish": 1, "neutral": 0}
    # 2 of 3 in (unanimous, majority).
    assert summary["consensus_rate_pct"] == 67
    assert summary["top3_tickers"] == ["MU", "WDC", "STX"]
    assert summary["roundtable_enabled"] is True
    assert summary["llm_calls"] == 80
    assert summary["cache_hit_pct"] == 30
    assert summary["duration_sec"] == 138


# ── 3. Filter by mode + market ────────────────────────────────────────


def test_history_filters_by_mode_and_market(alice_client, app_client):
    s = _store(app_client)
    aid = app_client["users"].alice.id
    _seed(s, task_id="t-us-agent", owner=aid, status="success",
          params={"market": "us", "gurus": ["x"], "mode": "agent",
                   "candidate_n": 10})
    _seed(s, task_id="t-cn-rt", owner=aid, status="success",
          params={"market": "cn", "gurus": ["x"], "mode": "agent_rt",
                   "with_roundtable": True, "candidate_n": 10})
    body_rt = alice_client.get("/api/screen/v3/history?mode=agent_rt").get_json()
    assert body_rt["items"]
    assert all(it["params"]["mode"] == "agent_rt" for it in body_rt["items"])

    body_us = alice_client.get("/api/screen/v3/history?market=us").get_json()
    assert body_us["items"]
    assert all(it["params"]["market"] == "us" for it in body_us["items"])


# ── 4. Pagination ─────────────────────────────────────────────────────


def test_history_pagination(alice_client, app_client):
    s = _store(app_client)
    aid = app_client["users"].alice.id
    for i in range(10):
        _seed(s, task_id=f"t-pg-{i}", owner=aid, status="success",
              params={"market": "us", "gurus": ["x"], "mode": "agent",
                       "candidate_n": 10})
    body = alice_client.get("/api/screen/v3/history?limit=3&offset=3").get_json()
    assert len(body["items"]) == 3
    assert body["total"] == 10
    assert body["offset"] == 3


# ── 5. Single-row prefill endpoint ────────────────────────────────────


def test_history_one_returns_params_for_prefill(alice_client, app_client):
    s = _store(app_client)
    aid = app_client["users"].alice.id
    _seed(s, task_id="t-pf-1", owner=aid, status="success",
          params={"nl_query": "AI 龙头", "market": "us", "candidate_n": 15,
                   "gurus": ["buffett", "graham"], "mode": "agent",
                   "with_roundtable": False})
    body = alice_client.get("/api/screen/v3/history/t-pf-1").get_json()
    assert body["params"]["nl_query"] == "AI 龙头"
    assert body["params"]["candidate_n"] == 15
    assert body["params"]["gurus"] == ["buffett", "graham"]
    assert body["params"]["with_roundtable"] is False


# ── 6. Cross-user single-row read is 404 ──────────────────────────────


def test_history_one_blocks_cross_user(bob_client, app_client):
    s = _store(app_client)
    _seed(s, task_id="t-alice-only",
          owner=app_client["users"].alice.id, status="success",
          params={"market": "us", "gurus": ["x"], "mode": "agent",
                   "candidate_n": 10})
    resp = bob_client.get("/api/screen/v3/history/t-alice-only")
    assert resp.status_code == 404


# ── 7. Default excludes running/pending ───────────────────────────────


def test_history_excludes_running_by_default(alice_client, app_client):
    s = _store(app_client)
    aid = app_client["users"].alice.id
    _seed(s, task_id="t-pending", owner=aid, status="pending",
          params={"market": "us", "gurus": ["x"], "mode": "agent",
                   "candidate_n": 10})
    body = alice_client.get("/api/screen/v3/history").get_json()
    assert body["items"] == []
    # include_failed=true still excludes pending — only success/failed/cancelled.
    body2 = alice_client.get("/api/screen/v3/history?include_failed=true").get_json()
    assert body2["items"] == []


# ── 8. Jinja shell renders for the /screener-v3/history route ─────────


def test_history_page_renders_html_shell(alice_client):
    resp = alice_client.get("/screener-v3/history")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'id="react-root"' in html
    # Same Vite entry as /screener-v3 — bundle loaded via <script type="module">.
    assert 'type="module"' in html


# ── Bonus: empty payload still returns a sane summary ─────────────────


def test_history_empty_candidates_payload(alice_client, app_client):
    s = _store(app_client)
    _seed(s, task_id="t-empty",
          owner=app_client["users"].alice.id, status="success",
          params={"market": "us", "gurus": ["x"], "mode": "agent",
                   "candidate_n": 10},
          result_payload={"candidates": []})
    body = alice_client.get("/api/screen/v3/history").get_json()
    summary = body["items"][0]["summary"]
    # Empty list returns just candidates_count (no avg/votes since n=0).
    assert summary == {"candidates_count": 0}
