"""Tests for the APScheduler-backed daily-snapshot wrapper.

The scheduler is an OS-level singleton (background thread + filesystem
lock). Tests reset it between runs, wire a callable that records calls,
and verify:

  * `start_if_primary` claims the lock and adds the cron job;
  * a second instance with the same lock path returns False;
  * `status()` exposes the next run time;
  * `run_now()` calls the snapshot fn synchronously;
  * stale lock (non-existent pid) is reclaimed.
"""

from __future__ import annotations

import os
import time

import pytest

from stock_trading_system.scheduler.daily_snapshot_scheduler import (
    DailySnapshotScheduler,
    take_snapshot_all_users,
)


@pytest.fixture(autouse=True)
def _reset_scheduler():
    DailySnapshotScheduler.reset()
    yield
    DailySnapshotScheduler.reset()


def test_start_if_primary_runs_only_once(tmp_path):
    """First start_if_primary wins; second one with the same lock no-ops."""
    fired: list[float] = []
    sched = DailySnapshotScheduler(lambda: fired.append(time.time()))
    lock = tmp_path / "scheduler.lock"
    assert sched.start_if_primary(lock_path=str(lock)) is True
    assert lock.exists()

    # Simulate a second worker booting with the same lock path.
    # We have to construct a fresh instance because singleton .get() guards it.
    DailySnapshotScheduler.reset()
    second = DailySnapshotScheduler(lambda: fired.append(time.time()))
    assert second.start_if_primary(lock_path=str(lock)) is False

    sched.shutdown()


def test_status_reports_next_run_time(tmp_path):
    sched = DailySnapshotScheduler(
        lambda: None,
        cron_kwargs={"hour": 16, "minute": 30, "timezone": "America/New_York"},
    )
    sched.start_if_primary(lock_path=str(tmp_path / "lock"))
    status = sched.status()
    assert status["running"] is True
    assert status["jobs"], "expected a daily_snapshot job entry"
    assert status["jobs"][0]["id"] == "daily_snapshot"
    next_run = status["jobs"][0]["next_run_time"]
    assert next_run, "next_run_time must be set"
    # 16:30 in America/New_York renders as -04:00 (EDT) or -05:00 (EST).
    assert "T16:30:" in next_run, f"unexpected next_run iso: {next_run}"
    assert next_run.endswith("-04:00") or next_run.endswith("-05:00"), \
        f"next_run_time should be in America/New_York, got {next_run}"
    sched.shutdown()


def test_run_now_invokes_callable(tmp_path):
    received: list[int] = []
    sched = DailySnapshotScheduler(lambda: received.append(1))
    sched.start_if_primary(lock_path=str(tmp_path / "lock"))
    sched.run_now()
    assert received == [1]
    sched.shutdown()


def test_stale_lock_is_reclaimed(tmp_path):
    """A lock owned by a non-existent pid should be reclaimable."""
    lock = tmp_path / "lock"
    # Use a pid we're confident is dead. PID -1 is invalid; pick a high
    # number that's almost certainly not running on the test host.
    lock.write_text("pid=999999 ts=2020-01-01T00:00:00Z\n")
    sched = DailySnapshotScheduler(lambda: None)
    assert sched.start_if_primary(lock_path=str(lock)) is True
    sched.shutdown()


def test_take_snapshot_all_users_iterates_active(tmp_path):
    """Driver fans out to every active user and calls take_snapshot."""
    captured: list[int] = []

    class _FakeUser:
        def __init__(self, uid):
            self.id = uid
            self.email = f"u{uid}@test"

    class _FakeRepo:
        def list_active(self): return [_FakeUser(1), _FakeUser(2), _FakeUser(7)]

    class _FakePM:
        def __init__(self, uid): self.uid = uid
        def take_snapshot(self, user_id=None): captured.append(user_id)

    result = take_snapshot_all_users(
        _FakeRepo(),
        portfolio_manager_factory=lambda uid: _FakePM(uid),
    )
    assert captured == [1, 2, 7]
    assert result["user_count"] == 3
    assert {r["user_id"] for r in result["results"]} == {1, 2, 7}
