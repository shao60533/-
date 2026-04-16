"""TaskCleanupScheduler tests."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from stock_trading_system.data.local_cache import LocalCache
from stock_trading_system.tasks.cleanup import TaskCleanupScheduler
from stock_trading_system.tasks.task_store import TaskStore, hash_params


def _mk_task(store: TaskStore, age_iso: str | None = None):
    tid = str(uuid.uuid4())
    row = {
        "id": tid, "type": "echo", "title": "t",
        "params_json": json.dumps({"x": 1}),
        "status": "success",
        "params_hash": hash_params("echo", {"x": 1}),
    }
    if age_iso:
        row["created_at"] = age_iso
    store.insert(row)
    return tid


@pytest.fixture
def store(tmp_path):
    return TaskStore(str(tmp_path / "tasks.db"))


@pytest.fixture
def cache(tmp_path):
    cfg = {"data_routing": {"cache_ttl": {"price_quote": 1}}}
    return LocalCache(str(tmp_path / "cache.db"), config=cfg)


# ── Synchronous one-shot ─────────────────────────────────────────────────────


def test_run_once_purges_expired_tasks(store):
    fresh = _mk_task(store)
    old = _mk_task(store, age_iso="2020-01-01 00:00:00")
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=3600)
    result = sched.run_once()
    assert result["tasks_deleted"] == 1
    assert store.get(fresh) is not None
    assert store.get(old) is None


def test_run_once_keeps_recent(store):
    _mk_task(store)
    _mk_task(store)
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=3600)
    result = sched.run_once()
    assert result["tasks_deleted"] == 0


def test_run_once_invokes_cache_cleanup(store, cache):
    cache.set_price("AAPL", {"last": 150})
    time.sleep(2.2)  # exceed 1s TTL
    sched = TaskCleanupScheduler(store, retention_days=30,
                                 interval_seconds=3600, cache=cache)
    result = sched.run_once()
    assert result["cache_deleted"] >= 1


def test_run_once_handles_store_error_gracefully(store):
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=3600)
    # Monkey-patch to raise
    store.cleanup_expired = lambda days: (_ for _ in ()).throw(RuntimeError("boom"))
    result = sched.run_once()
    assert result["tasks_deleted"] == -1  # error path returns -1 sentinel


# ── Background thread lifecycle ──────────────────────────────────────────────


def test_start_creates_daemon_thread(store):
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=60)
    sched.start()
    try:
        assert sched.is_alive()
    finally:
        sched.stop()
    assert not sched.is_alive()


def test_start_is_idempotent(store):
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=60)
    sched.start()
    sched.start()  # second call must be a no-op
    try:
        assert sched.is_alive()
    finally:
        sched.stop()


def test_stop_returns_quickly(store):
    """Sleep is interruptible — stop() shouldn't block for the full interval."""
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=3600)
    sched.start()
    start = time.perf_counter()
    sched.stop()
    elapsed = time.perf_counter() - start
    assert elapsed < 4, f"stop took {elapsed:.2f}s — interval blocking?"


# ── Min interval guard ───────────────────────────────────────────────────────


def test_minimum_interval_clamped(store):
    sched = TaskCleanupScheduler(store, retention_days=30, interval_seconds=1)
    assert sched._interval >= 60, "interval below 60s should be clamped"
