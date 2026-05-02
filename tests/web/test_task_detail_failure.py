"""GET /api/tasks/<id> exposes failure details correctly per viewer.

Owners and admins see ``error_message`` + ``error_trace``. Same-tenant
non-owners viewing a *shared* research task (analysis / screen / …) see
``error_message`` (the worker-wrapped human reason — safe), but
``error_trace`` is stripped because the raw traceback can leak file
paths, env values, or API key fragments. Private types stay 403 for
non-owner non-admin viewers (covered by the existing isolation tests in
``test_task_api.py``).
"""

from __future__ import annotations

import json
import uuid


def _seed_failed_task(
    app_client,
    *,
    task_type: str,
    owner_id: int,
    error_message: str = "Qwen API Key 未配置",
    error_trace: str = (
        'Traceback (most recent call last):\n'
        '  File "/Users/test/secret/path.py", line 42, in run\n'
        '    raise RuntimeError("HTTP 401")\n'
        'RuntimeError: HTTP 401 invalid_api_key sk-deadbeef-leaked\n'
    ),
) -> str:
    """Insert a failed task row owned by ``owner_id`` and return its id."""
    from stock_trading_system.web import app as app_module
    store = app_module._get_task_store()
    task_id = str(uuid.uuid4())
    store.insert({
        "id": task_id,
        "type": task_type,
        "title": f"failed {task_type}",
        "params_json": json.dumps({"ticker": "AAPL", "date": "2026-04-15"}),
        "status": "pending",
        "params_hash": "seed-failed-" + task_id[:8],
        "created_by": owner_id,
    })
    # Move to failed via TaskStore.update so error_message / error_trace land
    # on the row exactly the way TaskManager._fail would write them.
    store.update(
        task_id,
        status="failed",
        error_message=error_message,
        error_trace=error_trace,
        completed_at="2026-04-15T12:00:00Z",
        progress_step="market_analyst",
    )
    return task_id


def test_owner_sees_error_message_and_trace(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    task_id = _seed_failed_task(
        app_client, task_type="analysis", owner_id=users.alice.id,
    )

    rv = alice.get(f"/api/tasks/{task_id}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "failed"
    assert body["error_message"] == "Qwen API Key 未配置"
    # Owner can see the full developer trace.
    assert body.get("error_trace")
    assert "sk-deadbeef-leaked" in body["error_trace"]
    assert body["progress_step"] == "market_analyst"


def test_non_owner_on_shared_type_sees_message_but_no_trace(app_client):
    """Same-tenant viewer of a shared analysis task gets the friendly
    message but the raw traceback is stripped."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    task_id = _seed_failed_task(
        app_client, task_type="analysis", owner_id=users.bob.id,
    )

    rv = alice.get(f"/api/tasks/{task_id}")
    assert rv.status_code == 200, f"expected 200, got {rv.status_code}: {rv.get_data(as_text=True)}"
    body = rv.get_json()
    assert body["status"] == "failed"
    # Message is the human-readable reason — safe to share.
    assert body.get("error_message") == "Qwen API Key 未配置"
    # Trace is stripped: never exposed to non-owner / non-admin.
    assert "error_trace" not in body or not body.get("error_trace")
    # And critically the leaked token in the trace doesn't appear anywhere.
    serialized = json.dumps(body)
    assert "sk-deadbeef-leaked" not in serialized
    assert "/Users/test/secret/path.py" not in serialized


def test_admin_sees_error_trace_on_other_users_task(app_client):
    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    task_id = _seed_failed_task(
        app_client, task_type="analysis", owner_id=users.bob.id,
    )

    rv = admin.get(f"/api/tasks/{task_id}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body.get("error_trace")
    assert "sk-deadbeef-leaked" in body["error_trace"]


def test_owner_sees_message_when_trace_is_missing(app_client):
    """A failed task without a stored trace still shows error_message."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    task_id = _seed_failed_task(
        app_client, task_type="analysis", owner_id=users.alice.id,
        error_trace="",
    )

    rv = alice.get(f"/api/tasks/{task_id}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["error_message"] == "Qwen API Key 未配置"
    # Empty / missing trace is fine; the UI falls back gracefully.
    assert not body.get("error_trace")
