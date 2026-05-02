"""analysis-progress-truth-source v1.0 contract tests.

Locks the unified progress contract that the analysis worker, task
manager, and frontend (PipelineDAG + inbox row) all consume:

    1. ``progress_cb`` accepts a ``stage`` keyword that lands on the
       broadcast envelope as ``payload.stage``.
    2. ``task_progress`` envelope payload always carries ``task_id``
       (mirrored from ``id``), ``stage``, and ``status`` so the inbox
       can build a per-task progress map without inferring from event
       order.
    3. The analyzer's seven ``step_done`` events drive the row percent
       through 16 / 27 / 38 / 50 / 61 / 73 / 85 — not the legacy
       single-bump 15 / 85.
    4. All lifecycle events (``task_started`` / ``task_progress`` /
       ``task_completed`` / ``task_failed`` / ``task_cancelled``) are
       broadcast as the unified envelope so the live socket path
       reaches the frontend without depending on the catch-up replay.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_trading_system.tasks.task_manager import TaskManager
from stock_trading_system.tasks.task_store import TaskStore
from stock_trading_system.tasks.workers import make_analysis_worker


class RecordingSocketIO:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def emit(self, event, payload=None, **_):
        with self._lock:
            self.events.append((event, payload or {}))

    def by_event(self, name: str) -> list[dict]:
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
    m = TaskManager(store, socketio=sio, max_workers=1, default_idempotency_window=0)
    yield m
    m.shutdown(wait=True)


def _await(tm, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = tm.get(task_id)
        if t and t["status"] in ("success", "failed", "cancelled"):
            return t
        time.sleep(0.02)
    return tm.get(task_id)


# ── 1. Envelope contract ────────────────────────────────────────────────────


def test_emit_broadcasts_unified_envelope(tm, sio):
    """All lifecycle events MUST be broadcast as the canonical envelope
    {task_id, user_id, seq, event, payload, emitted_at}, NOT the raw
    payload. The frontend's ``subscribeTaskStream.onAny`` filters on
    ``"task_id" in env`` — raw payloads get dropped."""
    tm.register("report", lambda p, cb: {"content": "# ok"})
    t = tm.submit("report", {"type": "daily"})
    _await(tm, t["id"])

    for evt_name in ("task_created", "task_started", "task_completed"):
        emitted = sio.by_event(evt_name)
        assert emitted, f"missing emit for {evt_name}"
        env = emitted[0]
        # Envelope shape — top-level task_id is what the frontend filter looks at.
        assert env.get("task_id"), f"{evt_name}: envelope missing task_id"
        assert env.get("event") == evt_name, f"{evt_name}: event field mismatch"
        assert "payload" in env, f"{evt_name}: envelope missing payload"
        assert "seq" in env, f"{evt_name}: envelope missing seq"
        assert "emitted_at" in env, f"{evt_name}: envelope missing emitted_at"


def test_task_progress_envelope_carries_task_id_stage_status(tm, sio):
    """task_progress payload MUST expose task_id (mirrored from id),
    stage (structural step id), and status — those are the keys the
    inbox row state machine consumes."""
    def worker(params, cb):
        cb(20, "技术分析", stage="market")
        cb(60, "新闻分析", stage="news")
        return {}

    tm.register("report", worker)
    t = tm.submit("report", {"type": "daily"})
    _await(tm, t["id"])

    progress = sio.by_event("task_progress")
    assert len(progress) >= 2
    p0 = progress[0]["payload"]
    assert p0["task_id"] == t["id"]
    assert p0["id"] == t["id"]            # legacy alias
    assert p0["progress"] == 20
    assert p0["step"] == "技术分析"
    assert p0["stage"] == "market"
    assert p0["status"] == "running"


# ── 2. Analyzer pipeline → 5%→85% mapping ──────────────────────────────────


class _StreamingFakeAnalyzer:
    """Fake analyzer that emits the seven canonical step_done events
    so the worker's mapping callback can exercise the 5%→85% range."""

    def analyze(self, ticker, date, *, progress_cb=None, depth=None):
        steps = [
            "market", "social", "news",
            "fundamentals", "debate", "risk", "decision",
        ]
        if progress_cb is not None:
            progress_cb({"type": "pipeline_start", "total": len(steps)})
            for idx, sid in enumerate(steps):
                progress_cb({
                    "type": "step_done",
                    "step": sid,
                    "label": sid.upper(),
                    "index": idx,
                    "total": len(steps),
                })
            progress_cb({"type": "pipeline_done"})
        return SimpleNamespace(
            signal="BUY",
            market_report="bull", sentiment_report="ok",
            news_report="ok", fundamentals_report="ok",
            investment_debate={}, risk_assessment={}, trade_decision={},
        )


class _FakeStrategyEngine:
    def generate_advice(self, *_args, **_kw):
        return None


class _FakePortfolio:
    def get_holdings(self):
        return []


class _FakeRouter:
    def __init__(self):
        self.get_price = MagicMock(return_value={"last": 150})


def test_analyzer_step_done_drives_5_to_85_progress():
    """Each of the 7 step_done events MUST produce a task_progress call
    in the 5%→85% range. The classic 15%/85% bookends are gone; the
    seven steps now own the linear advance."""
    received: list[tuple[int, str | None, str | None]] = []

    def cb(pct, step=None, partial=None, *, stage=None):
        received.append((pct, step, stage))

    worker = make_analysis_worker(
        get_analyzer=lambda: _StreamingFakeAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakePortfolio(),
        get_router=lambda: _FakeRouter(),
    )
    worker({"ticker": "AAPL", "date": "2026-04-15"}, cb)

    pcts = [p for p, _step, _stage in received]
    # Init + pipeline_start both land at 5%.
    assert 5 in pcts
    # Each step_done lands on its mapped percent. With 7 steps spaced
    # across 5 → 85, the rounded sequence is 16 / 28 / 39 / 51 / 62 /
    # 74 / 85. Lock the first, midpoint, and last so a future change
    # to the spacing trips this assertion.
    assert 16 in pcts, f"missing first-step (16%) in {pcts}"
    assert 51 in pcts, f"missing midpoint (51%) in {pcts}"
    assert 85 in pcts, f"missing decision-done (85%) in {pcts}"
    # Worker bumps to 90 (advice) and 98 (finalize) after the analyzer.
    assert 90 in pcts
    assert 98 in pcts


def test_analyzer_step_done_carries_stage_id():
    """The structural step id (``market`` / ``decision``) lands on the
    progress envelope so the frontend can sync DAG + percent."""
    captured: list[str | None] = []

    def cb(pct, step=None, partial=None, *, stage=None):
        captured.append(stage)

    worker = make_analysis_worker(
        get_analyzer=lambda: _StreamingFakeAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakePortfolio(),
        get_router=lambda: _FakeRouter(),
    )
    worker({"ticker": "AAPL", "date": "2026-04-15"}, cb)

    # Structural ids from the analyzer must appear; ``init`` /
    # ``pipeline_done`` / ``advice`` / ``finalize`` come from the worker.
    assert "market" in captured
    assert "decision" in captured
    assert "pipeline_done" in captured
    assert "advice" in captured
    assert "finalize" in captured
