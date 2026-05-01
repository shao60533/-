"""Scheduler-control API contract tests.

The /api/scheduler/* surfaces are the operator's only window into whether
the daily-snapshot APScheduler job is actually running on a given box.
Pin the response shape and the admin-only run-now path.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def alice(app_client):
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


@pytest.fixture
def admin(app_client):
    users = app_client["users"]
    return app_client["make_client"](users.admin_email, users.admin_password)


def _start_scheduler():
    """Force-init the APScheduler singleton so /api/scheduler/status sees it.

    The conftest sets DISABLE_DAILY_SNAPSHOT_SCHEDULER=1 to keep test boots
    quiet; tests that exercise the status surface explicitly start it.
    """
    from stock_trading_system.scheduler.daily_snapshot_scheduler import (
        DailySnapshotScheduler,
    )
    DailySnapshotScheduler.reset()
    fired: list[int] = []

    def _snapshot():
        fired.append(1)
        return {"ok": True, "fired": len(fired)}

    sched = DailySnapshotScheduler.get(_snapshot)
    sched.start_if_primary()
    return sched, fired


@pytest.fixture
def started_scheduler(tmp_path, monkeypatch):
    # Use a tmp lock so we don't collide with a real dev box.
    monkeypatch.setenv("STOCK_CONFIG_DIR", str(tmp_path))
    sched, fired = _start_scheduler()
    yield sched, fired
    sched.shutdown()
    from stock_trading_system.scheduler.daily_snapshot_scheduler import (
        DailySnapshotScheduler,
    )
    DailySnapshotScheduler.reset()


def test_status_running_payload_shape(alice, started_scheduler):
    """Status surfaces running=True + a daily_snapshot job + last_run."""
    rv = alice.get("/api/scheduler/status")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["running"] is True
    job_ids = {j["id"] for j in body["jobs"]}
    assert "daily_snapshot" in job_ids
    daily = next(j for j in body["jobs"] if j["id"] == "daily_snapshot")
    assert daily["next_run_time"] is not None
    # last_run can be None on a fresh DB; just enforce the key exists.
    assert "last_run" in body


def test_status_inert_when_scheduler_not_started(alice):
    """Without start_if_primary(), the API still responds with running=False."""
    from stock_trading_system.scheduler.daily_snapshot_scheduler import (
        DailySnapshotScheduler,
    )
    DailySnapshotScheduler.reset()
    rv = alice.get("/api/scheduler/status")
    assert rv.status_code == 200
    body = rv.get_json()
    # running may be True from the legacy scheduler; what matters is jobs[]
    assert body["jobs"] == []


def test_run_now_admin_only(alice, admin, started_scheduler):
    """Non-admin POST → 403; admin POST → 200 + result echo."""
    # Alice (regular user) is rejected.
    rv = alice.post("/api/scheduler/run-now")
    assert rv.status_code == 403

    # Admin succeeds. The sched fixture's snapshot fn returns a small dict.
    rv = admin.post("/api/scheduler/run-now")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["result"]["ok"] is True
    sched, fired = started_scheduler
    assert fired == [1], "snapshot fn should have fired exactly once"


def test_run_now_503_when_uninitialized(admin):
    """If the scheduler singleton was never wired, run-now returns 503."""
    from stock_trading_system.scheduler.daily_snapshot_scheduler import (
        DailySnapshotScheduler,
    )
    DailySnapshotScheduler.reset()
    rv = admin.post("/api/scheduler/run-now")
    assert rv.status_code == 503
    assert rv.get_json()["error"]


def test_anonymous_status_redirects_or_401(app_client):
    anon = app_client["make_client"]()
    rv = anon.get("/api/scheduler/status")
    assert rv.status_code == 401
