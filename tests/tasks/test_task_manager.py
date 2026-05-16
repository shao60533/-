"""TaskManager unit tests — TM-1.2.* from TEST_CASES_ARCHITECTURE_UPGRADE."""

from __future__ import annotations

import threading
import time

import pytest

from stock_trading_system.tasks.task_manager import TaskManager
from stock_trading_system.tasks.task_store import TaskStore, hash_params


class RecordingSocketIO:
    """Capture WS emit calls for assertion."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def emit(self, event, payload=None, **_):
        with self._lock:
            self.events.append((event, payload or {}))

    def names(self) -> list[str]:
        with self._lock:
            return [e for e, _ in self.events]

    def by_name(self, name: str) -> list[dict]:
        with self._lock:
            return [p for n, p in self.events if n == name]


@pytest.fixture
def store(tmp_path):
    return TaskStore(str(tmp_path / "tasks.db"))


@pytest.fixture
def sio():
    return RecordingSocketIO()


@pytest.fixture
def tm(store, sio):
    m = TaskManager(store, socketio=sio, max_workers=3, default_idempotency_window=60)
    yield m
    m.shutdown(wait=True)


def _await(tm, task_id, timeout=5.0):
    """Block until task reaches terminal state and return the record."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = tm.get(task_id)
        if t and t["status"] in ("success", "failed", "cancelled"):
            return t
        time.sleep(0.02)
    return tm.get(task_id)


# ── TM-1.2.1 Worker registration ─────────────────────────────────────────────


def test_register_worker(tm):
    tm.register("echo", lambda p, cb: {"got": p})
    assert "echo" in tm.registered_types()


# ── TM-1.2.2 Submit creates a record ─────────────────────────────────────────


def test_submit_creates_task_record(tm, store):
    tm.register("echo", lambda p, cb: {"ok": True})
    t = tm.submit("echo", {"x": 1}, created_by=1)
    assert t["id"]
    assert t["type"] == "echo"
    assert t["status"] == "pending"
    assert store.get(t["id"])["type"] == "echo"


# ── TM-1.2.3 Auto title ──────────────────────────────────────────────────────


def test_auto_title_for_analysis(tm):
    tm.register("analysis", lambda p, cb: {})
    t = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    assert "AAPL" in t["title"]
    assert "分析" in t["title"]


# ── TM-1.2.4 Unknown task type fails fast ────────────────────────────────────


def test_unknown_task_type_fails_immediately(tm):
    t = tm.submit("nonexistent", {}, created_by=1)
    # Failure is synchronous inside submit when worker missing
    rec = tm.get(t["id"])
    assert rec["status"] == "failed"
    assert "Unknown task type" in rec["error_message"]


# ── TM-1.2.5 Worker success path ─────────────────────────────────────────────


def test_worker_success_writes_result(tm, store):
    def worker(params, cb):
        return {"ticker": params["ticker"], "date": "2026-04-15",
                "signal": "BUY", "market_report": "bull"}

    tm.register("analysis", worker)
    t = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    final = _await(tm, t["id"])
    assert final["status"] == "success"
    assert final["progress"] == 100
    assert final["result_ref"].startswith("analysis_history:")
    assert final["duration_ms"] is not None and final["duration_ms"] >= 0
    # Result retrievable
    result = tm.get_result(t["id"])
    assert result["ticker"] == "AAPL"
    assert result["signal"] == "BUY"


# ── TM-1.2.6 Worker exception → failed with trace ────────────────────────────


def test_worker_exception_marks_failed_with_trace(tm):
    def bad_worker(params, cb):
        raise ValueError("synthetic failure")

    tm.register("analysis", bad_worker)
    t = tm.submit("analysis", {"ticker": "ZZZZ"}, created_by=1)
    final = _await(tm, t["id"])
    assert final["status"] == "failed"
    assert "synthetic failure" in final["error_message"]
    assert final["error_trace"] and "ValueError" in final["error_trace"]


# ── TM-1.2.7 Progress callback flows ─────────────────────────────────────────


def test_progress_callback_persists_and_emits(tm, sio, store):
    def worker(params, cb):
        cb(20, "技术分析")
        cb(60, "新闻分析")
        return {}

    tm.register("report", worker)
    t = tm.submit("report", {"type": "daily"}, created_by=1)
    _await(tm, t["id"])
    # persisted max progress is 100 after success
    rec = store.get(t["id"])
    assert rec["progress"] == 100
    # WS events include progress updates
    progress_events = sio.by_name("task_progress")
    assert len(progress_events) >= 2
    assert progress_events[0]["progress"] == 20
    assert progress_events[0]["step"] == "技术分析"
    assert progress_events[1]["progress"] == 60


# ── TM-1.2.8 / 1.2.9 / 1.2.10 / 1.2.11 events order ──────────────────────────


def test_lifecycle_events_in_order(tm, sio):
    tm.register("report", lambda p, cb: {"content": "# hi"})
    t = tm.submit("report", {"type": "daily"}, created_by=1)
    _await(tm, t["id"])

    names = sio.names()
    # First event for this task is task_created
    assert names[0] == "task_created"
    assert "task_started" in names
    assert "task_completed" in names
    # Order: created < started < completed
    started_idx = names.index("task_started")
    completed_idx = names.index("task_completed")
    assert started_idx < completed_idx


def test_failed_event_emitted(tm, sio):
    tm.register("report", lambda p, cb: (_ for _ in ()).throw(RuntimeError("boom")))
    t = tm.submit("report", {}, created_by=1)
    _await(tm, t["id"])
    failed_evts = sio.by_name("task_failed")
    assert any(p["id"] == t["id"] for p in failed_evts)
    assert "boom" in failed_evts[0]["error_message"]


# ── TM-1.2.12 Idempotency hit ────────────────────────────────────────────────


def test_idempotency_reuses_recent_task(tm):
    calls = []
    tm.register("analysis", lambda p, cb: (calls.append(p), {"signal": "BUY"})[1])
    first = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    _await(tm, first["id"])
    second = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    assert second["id"] == first["id"], "should reuse existing task"
    assert len(calls) == 1, "worker should not run twice"


# ── TM-1.2.13 Out of window creates new ──────────────────────────────────────


def test_out_of_window_creates_new(tm, store):
    tm.register("analysis", lambda p, cb: {})
    first = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    _await(tm, first["id"])
    # Age the first record to fall outside any reasonable window.
    store.update(first["id"])  # noop, just to exercise path
    import sqlite3
    with sqlite3.connect(store._db_path) as c:
        c.execute("UPDATE tasks SET created_at = ? WHERE id = ?",
                  ("2020-01-01 00:00:00", first["id"]))
    second = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    assert second["id"] != first["id"]


# ── TM-1.2.14 Force-new via window=0 ─────────────────────────────────────────


def test_force_new_with_window_zero(tm):
    tm.register("analysis", lambda p, cb: {})
    first = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    _await(tm, first["id"])
    second = tm.submit("analysis", {"ticker": "AAPL"}, idempotency_window=0, created_by=1)
    assert second["id"] != first["id"]


# ── TM-1.2.15 Retry ──────────────────────────────────────────────────────────


def test_retry_creates_new_task_with_retry_of(tm):
    tm.register("analysis", lambda p, cb: (_ for _ in ()).throw(ValueError("x")))
    t = tm.submit("analysis", {"ticker": "AAPL"}, created_by=1)
    _await(tm, t["id"])
    retried = tm.retry(t["id"])
    assert retried["id"] != t["id"]
    assert retried["retry_of"] == t["id"]
    _await(tm, retried["id"])


# ── TM-1.2.16 Retry invalid id ───────────────────────────────────────────────


def test_retry_unknown_id_raises(tm):
    with pytest.raises(ValueError):
        tm.retry("definitely-not-a-real-id")


# ── TM-1.2.17 Cancel pending / success ───────────────────────────────────────


def test_cancel_pending_task(tm):
    # Saturate pool so new tasks queue up
    block = threading.Event()
    release = threading.Event()

    def slow(p, cb):
        block.set()
        release.wait(timeout=5)
        return {}

    tm.register("slow", slow)
    # Fill pool
    running_ids = [tm.submit("slow", {"i": i}, idempotency_window=0, created_by=1)["id"]
                   for i in range(3)]
    # Wait for at least one to actually start
    block.wait(timeout=2)
    pending = tm.submit("slow", {"i": 99}, idempotency_window=0, created_by=1)
    # pending is queued, not yet started
    ok = tm.cancel(pending["id"])
    assert ok is True
    assert tm.get(pending["id"])["status"] == "cancelled"
    release.set()
    for tid in running_ids:
        _await(tm, tid, timeout=6)


# ── TM-1.2.18 Cancel of completed returns False ──────────────────────────────


def test_cancel_completed_returns_false(tm):
    tm.register("noop", lambda p, cb: {})
    t = tm.submit("noop", {}, created_by=1)
    _await(tm, t["id"])
    assert tm.cancel(t["id"]) is False


# ── TM-1.2.19 Param hash stability covered in test_task_store ────────────────
# ── TM-1.2.20 Concurrent submission of distinct params ───────────────────────


def test_concurrent_independent_tasks(tm):
    results = {}

    def worker(params, cb):
        time.sleep(0.05)
        results[params["i"]] = params["i"] * 2
        return {"i": params["i"]}

    tm.register("par", worker)
    ids = [
        tm.submit("par", {"i": i}, idempotency_window=0, created_by=1)["id"]
        for i in range(3)
    ]
    for tid in ids:
        _await(tm, tid)
    assert results == {0: 0, 1: 2, 2: 4}


# ── TM-1.2.21 Pool capacity — later tasks queue ──────────────────────────────


def test_pool_capacity_queues_extra_tasks(store, sio):
    tm = TaskManager(store, socketio=sio, max_workers=2)
    try:
        start_latch = threading.Barrier(3, timeout=5)
        release = threading.Event()
        starts: list[int] = []

        def slow(params, cb):
            starts.append(params["i"])
            try:
                start_latch.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass  # third worker never starts until release
            release.wait(timeout=5)
            return {}

        tm.register("slow", slow)
        ids = [tm.submit("slow", {"i": i}, idempotency_window=0, created_by=1)["id"]
               for i in range(4)]

        # Give scheduler a moment
        time.sleep(0.2)
        # Only 2 workers should be running
        running_now = [tm.get(i) for i in ids if tm.get(i)["status"] == "running"]
        assert len(running_now) <= 2

        release.set()
        for i in ids:
            _await(tm, i, timeout=6)
        # All four tasks eventually ran
        assert sorted(starts) == [0, 1, 2, 3]
    finally:
        tm.shutdown(wait=True)


# ── TM-1.2.22 Startup recovers orphans ───────────────────────────────────────


def test_orphan_recovery_on_startup(tmp_path):
    store = TaskStore(str(tmp_path / "t.db"))
    from stock_trading_system.tasks.task_store import hash_params as _hp
    import json, uuid
    # Fake a running task from a "previous process"
    store.insert({
        "id": str(uuid.uuid4()), "type": "analysis", "title": "orphan",
        "params_json": json.dumps({"ticker": "AAPL"}),
        "status": "running", "params_hash": _hp("analysis", {"ticker": "AAPL"}),
    })
    tm = TaskManager(store, socketio=RecordingSocketIO(), max_workers=1)
    try:
        rows = tm.list(status="failed")
        assert any("服务中断" in (r.get("error_message") or "") for r in rows)
    finally:
        tm.shutdown(wait=True)


# ── Extra: get_result / delete / list passthrough ────────────────────────────


def test_get_result_returns_none_before_completion(tm, store):
    """Use a blocking worker so we can deterministically observe pending state."""
    release = threading.Event()

    def slow(p, cb):
        release.wait(timeout=5)
        return {"x": 1}

    tm.register("slow", slow)
    t = tm.submit("slow", {}, idempotency_window=0, created_by=1)
    # Worker is blocked → result_ref MUST still be None.
    row = store.get(t["id"])
    assert row["result_ref"] is None
    assert tm.get_result(t["id"]) is None
    release.set()
    _await(tm, t["id"])


def test_delete_passthrough(tm):
    tm.register("noop", lambda p, cb: {})
    t = tm.submit("noop", {}, created_by=1)
    _await(tm, t["id"])
    assert tm.delete(t["id"]) is True
    assert tm.get(t["id"]) is None


# ── _post_analysis_save: auto paper-trade drive (R-fix-9) ────────────────────


def test_post_analysis_save_drives_paper_trade(tm, monkeypatch, tmp_path):
    """When a worker returns _advice_payload + created_by, the post-save hook
    creates a paper-trade session, plan, and (best-effort) planned_orders.
    """
    from stock_trading_system.portfolio.database import PortfolioDatabase
    from stock_trading_system.strategy.paper_trader import PaperTradeStore

    db_path = str(tmp_path / "p.db")
    PortfolioDatabase(db_path)  # bootstrap analysis_history schema
    store = PaperTradeStore(db_path)

    monkeypatch.setattr(
        "stock_trading_system.config.get_config",
        lambda: {"portfolio": {"db_path": db_path}},
    )
    # Stub out the data router so we don't try to fetch a live price.
    import stock_trading_system.web.app as _app_mod

    monkeypatch.setattr(_app_mod, "_get_data_router", lambda: None,
                        raising=False)

    # Seed an analysis row matching analysis_id=1 so the FK / audit log is sane.
    pdb = PortfolioDatabase(db_path)
    aid = pdb.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": 7,
    })

    tm._post_analysis_save(f"analysis_history:{aid}", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": 7,
        "trade_decision": "Enter on breakout",
        "_advice_payload": {
            "advice": {
                "action": "BUY", "stop_loss": 140,
                "entry_price_low": 145, "entry_price_high": 150,
                "suggested_position_pct": 0.05,
            },
            "holdings_snapshot": "[]",
        },
    })

    sessions = store.list_ticker_sessions()
    assert any(s.get("ticker") == "AAPL" for s in sessions)
    import sqlite3
    with sqlite3.connect(db_path) as c:
        n_plans = c.execute(
            "SELECT COUNT(*) FROM paper_trade_plans"
        ).fetchone()[0]
        # the auto-driven session should be tagged with the requesting user.
        sess_user = c.execute(
            "SELECT user_id FROM paper_trade_sessions "
            "WHERE ticker = 'AAPL' AND is_system = 0"
        ).fetchone()
    assert n_plans >= 1
    assert sess_user is not None
    assert int(sess_user[0]) == 7


def test_post_analysis_save_paper_trade_failure_is_swallowed(
    tm, monkeypatch, tmp_path, caplog,
):
    """If process_analysis explodes, the analysis task still succeeds."""
    db_path = str(tmp_path / "p.db")

    def _boom(*a, **kw):
        raise RuntimeError("paper engine on fire")

    monkeypatch.setattr(
        "stock_trading_system.strategy.paper_trader.process_analysis", _boom,
    )
    monkeypatch.setattr(
        "stock_trading_system.config.get_config",
        lambda: {"portfolio": {"db_path": db_path}},
    )

    # Seed analysis row so save_user_advice (step 1) succeeds.
    from stock_trading_system.portfolio.database import PortfolioDatabase
    pdb = PortfolioDatabase(db_path)
    aid = pdb.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": 7,
    })

    import logging
    caplog.set_level(logging.WARNING)
    # MUST NOT raise — paper trade is best-effort.
    tm._post_analysis_save(f"analysis_history:{aid}", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": 7,
        "_advice_payload": {
            "advice": {"action": "BUY"}, "holdings_snapshot": "[]",
        },
    })
    assert any(
        "auto paper-trade" in (r.message or "")
        or "paper engine on fire" in (r.message or "")
        for r in caplog.records
    )
