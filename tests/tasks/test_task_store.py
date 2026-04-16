"""TaskStore unit tests — covers TS-1.1.* from TEST_CASES_ARCHITECTURE_UPGRADE."""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest

from stock_trading_system.tasks.task_store import (
    TaskStore, hash_params, now_iso,
)


def _mk_task(
    task_id: str | None = None,
    task_type: str = "analysis",
    title: str = "测试任务",
    params: dict | None = None,
    status: str = "pending",
    params_hash: str | None = None,
) -> dict:
    params = params if params is not None else {"ticker": "AAPL"}
    return {
        "id": task_id or str(uuid.uuid4()),
        "type": task_type,
        "title": title,
        "params_json": json.dumps(params, ensure_ascii=False),
        "status": status,
        "params_hash": params_hash or hash_params(task_type, params),
    }


@pytest.fixture
def store(tmp_path):
    return TaskStore(str(tmp_path / "tasks.db"))


# ── TS-1.1.1 ──────────────────────────────────────────────────────────────────


def test_insert_and_get(store):
    t = _mk_task()
    store.insert(t)
    got = store.get(t["id"])
    assert got is not None
    assert got["id"] == t["id"]
    assert got["status"] == "pending"
    assert got["created_at"]  # auto-filled


# ── TS-1.1.2 ──────────────────────────────────────────────────────────────────


def test_update_fields(store):
    t = _mk_task()
    store.insert(t)
    started = now_iso()
    store.update(t["id"], status="running", started_at=started, progress=30)
    got = store.get(t["id"])
    assert got["status"] == "running"
    assert got["started_at"] == started
    assert got["progress"] == 30
    assert got["title"] == t["title"]  # unchanged


def test_update_ignores_unknown_fields(store):
    t = _mk_task()
    store.insert(t)
    # Attempt to tamper with id/type should be silently dropped.
    store.update(t["id"], id="HACKED", type="hacked", status="running")
    got = store.get(t["id"])
    assert got["id"] == t["id"]
    assert got["type"] == "analysis"
    assert got["status"] == "running"


# ── TS-1.1.3, TS-1.1.4 ────────────────────────────────────────────────────────


def test_list_filter_by_type_and_status(store):
    for i in range(3):
        store.insert(_mk_task(task_type="analysis", status="success"))
    for i in range(4):
        store.insert(_mk_task(task_type="screen", status="success"))
    for i in range(2):
        store.insert(_mk_task(task_type="screen", status="failed"))

    by_type = store.list(task_type="analysis")
    assert len(by_type) == 3
    assert all(r["type"] == "analysis" for r in by_type)

    by_status = store.list(status="failed")
    assert len(by_status) == 2
    assert all(r["status"] == "failed" for r in by_status)

    combo = store.list(task_type="screen", status="failed")
    assert len(combo) == 2


# ── TS-1.1.5 ──────────────────────────────────────────────────────────────────


def test_list_pagination(store):
    # Use varying created_at via small sleeps to guarantee ordering
    ids = []
    for i in range(15):
        t = _mk_task()
        ids.append(t["id"])
        store.insert(t)
    page1 = store.list(limit=10, offset=0)
    page2 = store.list(limit=10, offset=10)
    assert len(page1) == 10
    assert len(page2) == 5
    # No overlap
    assert not (set(r["id"] for r in page1) & set(r["id"] for r in page2))


# ── TS-1.1.6 ──────────────────────────────────────────────────────────────────


def test_list_order_descending(store):
    first = _mk_task(title="older")
    store.insert(first)
    time.sleep(1.01)  # created_at is second-precision
    later = _mk_task(title="newer")
    store.insert(later)
    rows = store.list()
    assert rows[0]["id"] == later["id"], "newest should be first"
    assert rows[1]["id"] == first["id"]


# ── TS-1.1.7, TS-1.1.8, TS-1.1.9 ──────────────────────────────────────────────


def test_idempotency_find_recent_hit(store):
    params = {"ticker": "AAPL", "date": "2026-04-15"}
    h = hash_params("analysis", params)
    t = _mk_task(params=params, params_hash=h, status="success")
    store.insert(t)
    hit = store.find_recent_by_hash(h, window_seconds=60)
    assert hit is not None
    assert hit["id"] == t["id"]


def test_idempotency_out_of_window(store):
    params = {"ticker": "AAPL"}
    h = hash_params("analysis", params)
    t = _mk_task(params=params, params_hash=h, status="success")
    # Make the record 2 hours old so a 60-second window excludes it.
    t["created_at"] = "2020-01-01 00:00:00"
    store.insert(t)
    miss = store.find_recent_by_hash(h, window_seconds=60)
    assert miss is None


def test_idempotency_status_filter(store):
    params = {"ticker": "AAPL"}
    h = hash_params("analysis", params)
    t = _mk_task(params=params, params_hash=h, status="failed")
    store.insert(t)
    # Looking only for success — failed should not match
    miss = store.find_recent_by_hash(h, 60, statuses=("success",))
    assert miss is None
    # But an explicit failed filter matches
    hit = store.find_recent_by_hash(h, 60, statuses=("failed",))
    assert hit is not None


# ── TS-1.1.10, TS-1.1.11 ──────────────────────────────────────────────────────


def test_save_and_load_analysis_result(store):
    t = _mk_task(task_type="analysis")
    store.insert(t)
    result = {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "market_report": "bullish trend",
        "fundamentals_report": "strong earnings",
        "advice": {"action": "BUY", "confidence": "high"},
    }
    ref = store.save_result("analysis", t["id"], result)
    assert ref.startswith("analysis_history:")
    loaded = store.load_result(ref)
    assert loaded is not None
    assert loaded["ticker"] == "AAPL"
    assert loaded["signal"] == "BUY"
    assert "strong earnings" in loaded["fundamentals_report"]


def test_save_and_load_screen_result(store):
    t = _mk_task(task_type="screen")
    store.insert(t)
    result = {
        "market": "us", "strategy": "growth",
        "results": [{"ticker": "NVDA", "score": 87}],
    }
    ref = store.save_result("screen", t["id"], result)
    assert ref.startswith("screen_results:")
    loaded = store.load_result(ref)
    assert json.loads(loaded["results_json"])[0]["ticker"] == "NVDA"


def test_save_and_load_backtest_result(store):
    t = _mk_task(task_type="backtest")
    store.insert(t)
    result = {
        "ticker": "AAPL", "strategy_id": "sma", "period": "1y",
        "initial_capital": 100000,
        "metrics": {"total_return": 0.23, "max_drawdown": -0.12},
        "equity_curve": [{"date": "2026-01-01", "value": 100000}],
        "trades": [{"date": "2026-01-05", "action": "BUY"}],
    }
    ref = store.save_result("backtest", t["id"], result)
    assert ref.startswith("backtest_results:")
    loaded = store.load_result(ref)
    assert loaded["ticker"] == "AAPL"


def test_load_bad_ref_returns_none(store):
    assert store.load_result("") is None
    assert store.load_result("no_colon") is None
    assert store.load_result("bogus_table:1") is None


def test_generic_result_fallback(store):
    t = _mk_task(task_type="report")
    store.insert(t)
    ref = store.save_result("report", t["id"], {"content": "# Hello"})
    assert ref.startswith("task_results_generic:")
    loaded = store.load_result(ref)
    assert loaded is not None
    assert loaded["content"] == "# Hello"


# ── TS-1.1.12 ─────────────────────────────────────────────────────────────────


def test_cleanup_expired(store):
    old = _mk_task()
    old["created_at"] = "2020-01-01 00:00:00"
    store.insert(old)
    fresh = _mk_task()
    store.insert(fresh)
    deleted = store.cleanup_expired(days=30)
    assert deleted == 1
    assert store.get(old["id"]) is None
    assert store.get(fresh["id"]) is not None


# ── TS-1.1.13 ─────────────────────────────────────────────────────────────────


def test_status_index_fast_lookup(store):
    # Insert many rows then query — should remain fast (<200ms for 500 rows is
    # a very loose bound; actual target is <50ms, which we easily hit locally).
    for _ in range(500):
        store.insert(_mk_task(status="success"))
    for _ in range(20):
        store.insert(_mk_task(status="running"))
    start = time.perf_counter()
    rows = store.list(status="running", limit=50)
    elapsed = time.perf_counter() - start
    assert len(rows) == 20
    assert elapsed < 0.2, f"list(status='running') took {elapsed:.3f}s"


# ── TS-1.1.14 ─────────────────────────────────────────────────────────────────


def test_unicode_and_emoji_round_trip(store):
    t = _mk_task(
        title="🚀 AAPL 分析 · 2026-04-15",
        params={"ticker": "AAPL", "notes": "看涨信号 📈"},
    )
    store.insert(t)
    got = store.get(t["id"])
    assert got["title"] == t["title"]
    params_back = json.loads(got["params_json"])
    assert params_back["notes"] == "看涨信号 📈"


# ── TS-1.1.15 ─────────────────────────────────────────────────────────────────


def test_concurrent_writes_do_not_lock(store):
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(20):
                store.insert(_mk_task())
        except Exception as e:  # noqa: BLE001 — want to capture any error
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, f"Unexpected errors: {errors}"
    assert len(store.list(limit=100)) == 60


# ── Additional: hash stability, delete, orphan recovery, counts ─────────────


def test_hash_params_stable_across_key_order():
    a = hash_params("analysis", {"ticker": "AAPL", "date": "2026-04-15"})
    b = hash_params("analysis", {"date": "2026-04-15", "ticker": "AAPL"})
    assert a == b


def test_hash_params_varies_by_type():
    a = hash_params("analysis", {"ticker": "AAPL"})
    b = hash_params("screen", {"ticker": "AAPL"})
    assert a != b


def test_delete(store):
    t = _mk_task()
    store.insert(t)
    assert store.delete(t["id"]) is True
    assert store.get(t["id"]) is None
    assert store.delete(t["id"]) is False


def test_mark_orphaned_running_as_failed(store):
    a = _mk_task(status="running")
    b = _mk_task(status="pending")
    c = _mk_task(status="success")
    for t in (a, b, c):
        store.insert(t)
    n = store.mark_orphaned_running_as_failed(reason="test restart")
    assert n == 2
    assert store.get(a["id"])["status"] == "failed"
    assert store.get(a["id"])["error_message"] == "test restart"
    assert store.get(b["id"])["status"] == "failed"
    assert store.get(c["id"])["status"] == "success"


def test_count_by_status(store):
    for s in ["success", "success", "failed", "running"]:
        store.insert(_mk_task(status=s))
    counts = store.count_by_status()
    assert counts.get("success") == 2
    assert counts.get("failed") == 1
    assert counts.get("running") == 1
