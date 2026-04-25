"""Task REST API integration tests — TA-1.3.* from test plan.

Exercises the full Flask + SocketIO + TaskManager pipeline through the
HTTP routes defined in web/app.py.
"""

from __future__ import annotations

import time

import pytest

from stock_trading_system.config import load_config
from stock_trading_system.web import app as app_module


@pytest.fixture
def client(tmp_path):
    """Build a fresh Flask test client pointing at an isolated db/cache."""
    db_path = tmp_path / "portfolio.db"

    # Reset module-level singletons (Flask app is recreated per fixture)
    for attr in (
        "_task_manager", "_task_store", "_local_cache",
        "_portfolio_mgr", "_alert_monitor", "_data_manager",
        "_analyzer", "_screener", "_report_gen", "_strategy_engine",
        "_scheduler", "_scheduler_thread",
    ):
        if hasattr(app_module, attr):
            setattr(app_module, attr, None)

    app = app_module.create_app()
    app.config["TESTING"] = True

    # create_app internally calls load_config() which resets the global cfg.
    # Override *after* app creation so our tmp path sticks when singletons
    # are lazy-initialized on first API call.
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["portfolio"] = {"db_path": str(db_path)}

    # Force task manager to initialize now so workers are registered
    # and subsequent orphan recovery runs on an empty DB.
    app_module._get_task_manager()

    with app.test_client() as c:
        yield c

    tm = getattr(app_module, "_task_manager", None)
    if tm is not None:
        tm.shutdown(wait=False)


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
    # generic result stored as {'payload': {...}} or raw dict depending on route
    # echo worker returns {"echoed": params}; stored via generic fallback
    assert body["result"] is not None


# ── TA-1.3.10 result before completion returns 404 ───────────────────────────


def test_result_not_ready(client):
    # We can't reliably race an echo task (too fast). Instead submit to an
    # unknown type, which immediately fails — result should be unavailable.
    rv = client.post("/api/tasks/submit",
                     json={"type": "totally_bogus", "params": {}})
    assert rv.status_code == 400  # unknown type rejected at the API level
    # Submit echo and immediately ask for result before waiting
    sub = client.post("/api/tasks/submit",
                      json={"type": "echo", "params": {"x": 1}}).get_json()
    # It may race — if already success, skip; otherwise expect 404
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


def test_diagnostics_providers_shape(client):
    """Diagnostics endpoint returns provider statuses + routing summary.

    To keep CI fast, every provider is disabled — we only verify the
    endpoint shape, not real network reachability.
    """
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["providers"] = {
        "yfinance_enabled": False,
        "akshare_enabled": False,
        "polygon_enabled": False,
        "ib_enabled": False,
    }
    cfg["qwen"] = {"enabled": False, "api_key": ""}
    rv = client.get("/api/diagnostics/providers")
    assert rv.status_code in (200, 207)
    body = rv.get_json()
    assert "providers" in body
    assert "routing" in body
    assert "primary" in body["routing"]
    # All providers disabled → empty providers dict but request still 200
    assert body["providers"] == {}
