"""Task REST API integration tests — TA-1.3.* from test plan.

Exercises the full Flask + SocketIO + TaskManager pipeline through the
HTTP routes defined in web/app.py. Authenticated as canonical 'alice'
user via the shared ``app_client`` fixture.
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def client(app_client):
    """Logged-in alice client; default actor for every TA-1.3.* case."""
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


def _await_status(client, task_id, terminal={"success", "failed", "cancelled"},
                  timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rv = client.get(f"/api/tasks/{task_id}")
        if rv.status_code == 200 and rv.get_json()["status"] in terminal:
            return rv.get_json()
        time.sleep(0.02)
    return client.get(f"/api/tasks/{task_id}").get_json()


# ── TA-1.3.1 submit valid ─────────────────────────────────────────────────────


def test_submit_echo_task(client):
    rv = client.post("/api/tasks/submit", json={
        "type": "echo", "params": {"hello": "world"},
    })
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["id"]
    assert body["type"] == "echo"
    assert body["status"] in ("pending", "running", "success")


# ── TA-1.3.2 submit unknown type ──────────────────────────────────────────────


def test_submit_unknown_type(client):
    rv = client.post("/api/tasks/submit", json={"type": "totally_bogus"})
    assert rv.status_code == 400
    assert "Unknown" in rv.get_json()["error"]


def test_submit_missing_type(client):
    rv = client.post("/api/tasks/submit", json={})
    assert rv.status_code == 400


# ── TA-1.3.3~6 list + filtering + pagination ────────────────────────────────


def test_list_basic(client):
    client.post("/api/tasks/submit", json={"type": "echo", "params": {"i": 1}})
    rv = client.get("/api/tasks")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_list_filter_by_type(client):
    client.post("/api/tasks/submit", json={"type": "echo", "params": {"i": 2}})
    rv = client.get("/api/tasks?type=echo")
    items = rv.get_json()["items"]
    assert all(t["type"] == "echo" for t in items)


def test_list_filter_by_status_failed_absent(client):
    client.post("/api/tasks/submit", json={"type": "echo", "params": {"i": 3}})
    rv = client.get("/api/tasks?status=failed")
    assert rv.status_code == 200
    assert rv.get_json()["items"] == []


def test_list_pagination_params(client):
    for i in range(5):
        client.post("/api/tasks/submit",
                    json={"type": "echo", "params": {"k": i},
                          "title": f"t{i}"})
    rv = client.get("/api/tasks?limit=2&offset=0")
    body = rv.get_json()
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) <= 2


def test_list_unknown_scope_falls_back_to_mine(client):
    """Typoed scope must never bypass filtering and leak other users' tasks."""
    client.post("/api/tasks/submit", json={"type": "echo", "params": {"k": 1}})
    rv = client.get("/api/tasks?scope=my")  # typo: "my" instead of "mine"
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["scope"] == "mine"


# ── TA-1.3.7 detail ───────────────────────────────────────────────────────────


def test_detail(client):
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {"a": 1}}).get_json()
    _await_status(client, sub["id"])
    rv = client.get(f"/api/tasks/{sub['id']}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["id"] == sub["id"]
    assert "params_json" in body


# ── TA-1.3.8 missing id ───────────────────────────────────────────────────────


def test_detail_not_found(client):
    rv = client.get("/api/tasks/bogus-id-does-not-exist")
    assert rv.status_code == 404


# ── TA-1.3.9 result after success ─────────────────────────────────────────────


def test_result_after_success(client):
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {"k": "v"}}).get_json()
    _await_status(client, sub["id"])
    rv = client.get(f"/api/tasks/{sub['id']}/result")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "task" in body and "result" in body
    assert body["result"] is not None


# ── TA-1.3.10 result before completion returns 404 ───────────────────────────


def test_result_not_ready(client):
    rv = client.post("/api/tasks/submit",
                     json={"type": "totally_bogus", "params": {}})
    assert rv.status_code == 400
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {"x": 1}}).get_json()
    detail = client.get(f"/api/tasks/{sub['id']}").get_json()
    if detail["status"] != "success":
        rv = client.get(f"/api/tasks/{sub['id']}/result")
        assert rv.status_code == 404


# ── TA-1.3.11 retry ───────────────────────────────────────────────────────────


def test_retry(client):
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {"k": "v"}}).get_json()
    _await_status(client, sub["id"])
    rv = client.post(f"/api/tasks/{sub['id']}/retry")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["id"] != sub["id"]
    assert body["retry_of"] == sub["id"]


def test_retry_unknown(client):
    rv = client.post("/api/tasks/bogus/retry")
    assert rv.status_code == 404


# ── TA-1.3.12 cancel ─────────────────────────────────────────────────────────


def test_cancel_completed_is_conflict(client):
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {}}).get_json()
    _await_status(client, sub["id"])
    rv = client.post(f"/api/tasks/{sub['id']}/cancel")
    assert rv.status_code == 409


def test_cancel_missing(client):
    rv = client.post("/api/tasks/nope/cancel")
    assert rv.status_code == 404


# ── TA-1.3.13 delete ─────────────────────────────────────────────────────────


def test_delete_record(client):
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {}}).get_json()
    _await_status(client, sub["id"])
    rv = client.delete(f"/api/tasks/{sub['id']}")
    assert rv.status_code == 200
    rv2 = client.get(f"/api/tasks/{sub['id']}")
    assert rv2.status_code == 404


def test_delete_missing(client):
    rv = client.delete("/api/tasks/not-a-real-id")
    assert rv.status_code == 404


# ── Stats endpoint (sanity) ──────────────────────────────────────────────────


def test_stats_endpoint(client):
    client.post("/api/tasks/submit", json={"type": "echo", "params": {}})
    rv = client.get("/api/tasks/stats")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "by_status" in body
    assert "echo" in body["registered_types"]


# ── /api/tasks/cleanup ────────────────────────────────────────────────────────


def test_cleanup_endpoint(client):
    """Cleanup endpoint returns counts removed (likely zero on a fresh DB)."""
    rv = client.post("/api/tasks/cleanup")
    assert rv.status_code == 200
    body = rv.get_json()
    assert "tasks_deleted" in body
    assert "cache_deleted" in body


# ── /api/diagnostics/providers ────────────────────────────────────────────────


def test_diagnostics_providers_shape(app_client):
    """Diagnostics endpoint returns provider statuses + routing summary.

    hardening-iteration-v1 P0: this endpoint now requires admin — its
    truncated error messages can leak provider names / proxy URLs to
    plain users. Test uses admin_client (was: alice → 403).
    """
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["providers"] = {
        "yfinance_enabled": False,
        "akshare_enabled": False,
        "polygon_enabled": False,
        "ib_enabled": False,
        "schwab_enabled": False,
    }
    cfg["qwen"] = {"enabled": False, "api_key": ""}
    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    rv = admin.get("/api/diagnostics/providers")
    assert rv.status_code in (200, 207)
    body = rv.get_json()
    assert "providers" in body
    assert "routing" in body
    assert "primary" in body["routing"]
    # OpenRouter is always reported (even when disabled, as a "not
    # configured" entry) — the test's intent is "no data-provider
    # succeeded when every cfg switch is off". Assert no provider is
    # ok=True rather than "the dict is empty".
    assert not any(v.get("ok") for v in body["providers"].values())


# ── Cross-user task isolation ────────────────────────────────────────────────
#
# These tests insert task rows directly through TaskStore rather than via
# /api/tasks/submit. We're verifying the HTTP access-control middleware, so
# spawning real workers (paper_backfill in particular runs a multi-second
# DB-backed backfill) just makes the suite slower and adds I/O-on-closed-file
# noise at pytest teardown.


def _seed_task_row(app_client, task_type, owner_id, status="success"):
    """Insert a task owned by ``owner_id`` and return its id."""
    import json
    import uuid
    from stock_trading_system.web import app as app_module
    store = app_module._get_task_store()
    task_id = str(uuid.uuid4())
    store.insert({
        "id": task_id,
        "type": task_type,
        "title": f"seed {task_type}",
        "params_json": json.dumps({"ticker": "TEST"}),
        "status": status,
        "params_hash": "seed-" + task_id[:8],
        "created_by": owner_id,
    })
    return task_id


@pytest.mark.parametrize(
    "ttype",
    ["meta_evolution", "qwen_fundamentals", "agent_score_update", "echo"],
)
def test_alice_cannot_read_bob_unclassified_task(app_client, ttype):
    """Types that are neither SHARED nor PRIVATE must default to owner-only.

    Without this safeguard, adding a new task type to the codebase would
    silently expose it across users until somebody remembers to update the
    private-types list.
    """
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob_task_id = _seed_task_row(app_client, ttype, users.bob.id)

    rv = alice.get(f"/api/tasks/{bob_task_id}")
    assert rv.status_code == 403, f"{ttype}: expected 403, got {rv.status_code}"
    assert rv.get_json()["error"] == "forbidden"


@pytest.mark.parametrize(
    "ttype", ["paper_trade", "paper_backfill", "batch_analysis"],
)
def test_alice_cannot_read_bob_private_task(app_client, ttype):
    """Documented PRIVATE types stay owner-only."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob_task_id = _seed_task_row(app_client, ttype, users.bob.id)

    rv = alice.get(f"/api/tasks/{bob_task_id}")
    assert rv.status_code == 403, f"{ttype}: expected 403, got {rv.status_code}"


@pytest.mark.parametrize(
    "ttype",
    ["analysis", "screen", "screen_v2", "screen_v3", "backtest", "report"],
)
def test_alice_can_read_bob_shared_task(app_client, ttype):
    """SHARED research types are readable by any logged-in user."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob_task_id = _seed_task_row(app_client, ttype, users.bob.id)

    rv = alice.get(f"/api/tasks/{bob_task_id}")
    assert rv.status_code == 200, f"{ttype}: expected 200, got {rv.status_code}"
    body = rv.get_json()
    assert body["id"] == bob_task_id


def test_alice_cannot_mutate_bob_shared_task(app_client):
    """Even when SHARED is readable, cancel/delete/retry require owner."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    # Pending → cancel/delete attempts hit ownership before state check
    pending_id = _seed_task_row(app_client, "analysis", users.bob.id, status="pending")
    assert alice.post(f"/api/tasks/{pending_id}/cancel").status_code == 403
    assert alice.delete(f"/api/tasks/{pending_id}").status_code == 403

    # Failed → retry attempt
    failed_id = _seed_task_row(app_client, "analysis", users.bob.id, status="failed")
    assert alice.post(f"/api/tasks/{failed_id}/retry").status_code == 403


def test_admin_can_read_bob_private_task(app_client):
    """Admin role bypasses the type-based access gate."""
    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    bob_task_id = _seed_task_row(app_client, "paper_backfill", users.bob.id)

    rv = admin.get(f"/api/tasks/{bob_task_id}")
    assert rv.status_code == 200
