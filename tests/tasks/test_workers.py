"""Worker tests — WK-1.4.*

Use fakes for analyzer/screener/report_gen so tests don't hit external APIs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_trading_system.tasks.task_manager import TaskManager
from stock_trading_system.tasks.task_store import TaskStore
from stock_trading_system.tasks.workers import (
    WorkerDeps, echo_worker, make_analysis_worker, make_backtest_worker,
    make_qwen_fundamentals_worker, make_qwen_news_worker, make_report_worker,
    make_screen_v3_worker, make_screen_worker, register_default_workers,
)


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeAnalyzer:
    def __init__(self, signal="BUY"):
        self.signal = signal
        self.called_with = None

    def analyze(self, ticker, date):
        self.called_with = (ticker, date)
        return SimpleNamespace(
            signal=self.signal,
            market_report="bull trend",
            sentiment_report="positive",
            news_report="quiet week",
            fundamentals_report="strong",
            investment_debate={"bull": "good", "bear": "ok"},
            risk_assessment={"risk": "low"},
            trade_decision={"action": "BUY"},
        )


class FakeStrategyEngine:
    def generate_advice(self, result, holdings, current_price):
        return SimpleNamespace(
            action="BUY", confidence="high",
            suggested_position_pct=10,
            entry_price_low=145, entry_price_high=155,
            stop_loss=140, take_profit=170,
            reasoning="alignment", risk_warning=None,
        )


class FakePortfolio:
    def get_holdings(self):
        return []


class FakeRouter:
    def __init__(self):
        self.get_price = MagicMock(return_value={"last": 150})
        self.get_fundamentals = MagicMock(return_value={
            "ticker": "AAPL", "pe_ratio": 28.5, "market_cap": 3e12,
            "pb_ratio": 40, "eps": 6.5,
        })
        self.get_news = MagicMock(return_value=[
            {"title": "News", "url": "https://x.com/n", "date": "2026-04-14",
             "source": "X", "summary": "ok"}
        ])


class FakeScreener:
    def screen(self, market="us", strategy="growth"):
        return [{"ticker": "NVDA", "score": 87, "name": "NVIDIA"}]


class FakeReportGen:
    def daily_report(self): return "# Daily\n\nContent"
    def weekly_report(self): return "# Weekly"
    def monthly_report(self): return "# Monthly"
    def stock_report(self, ticker): return f"# {ticker} Report"


# ── WK-1.4.1 analysis worker success ─────────────────────────────────────────


def test_analysis_worker_success():
    progress = []
    cb = lambda p, s=None, partial=None: progress.append((p, s))
    worker = make_analysis_worker(
        get_analyzer=lambda: FakeAnalyzer(signal="BUY"),
        get_strategy_engine=lambda: FakeStrategyEngine(),
        get_portfolio=lambda: FakePortfolio(),
        get_router=lambda: FakeRouter(),
    )
    result = worker({"ticker": "AAPL", "date": "2026-04-15"}, cb)
    assert result["signal"] == "BUY"
    assert result["ticker"] == "AAPL"
    assert result["advice"]["action"] == "BUY"
    assert any(p[0] >= 80 for p in progress)


# ── WK-1.4.2 analysis worker reports several progress steps ─────────────────


def test_analysis_worker_progress_milestones():
    steps = []
    cb = lambda p, s=None, partial=None: steps.append((p, s))
    worker = make_analysis_worker(
        get_analyzer=lambda: FakeAnalyzer(),
        get_strategy_engine=lambda: FakeStrategyEngine(),
        get_portfolio=lambda: FakePortfolio(),
        get_router=lambda: FakeRouter(),
    )
    worker({"ticker": "AAPL"}, cb)
    # Expect at least: init, start, advice, finalize
    assert len(steps) >= 3


# ── WK-1.4.3 analysis worker invalid ticker ──────────────────────────────────


def test_analysis_worker_rejects_empty_ticker():
    worker = make_analysis_worker(
        get_analyzer=lambda: FakeAnalyzer(),
        get_strategy_engine=lambda: FakeStrategyEngine(),
        get_portfolio=lambda: FakePortfolio(),
        get_router=lambda: FakeRouter(),
    )
    with pytest.raises(ValueError, match="ticker"):
        worker({"ticker": ""}, lambda *a, **k: None)


# ── WK-1.4.4 screen worker success ───────────────────────────────────────────


def test_screen_worker_success():
    cb_calls = []
    worker = make_screen_worker(get_screener=lambda: FakeScreener())
    result = worker({"market": "us", "strategy": "growth"},
                    lambda p, s=None, partial=None: cb_calls.append(p))
    assert result["count"] == 1
    assert result["results"][0]["ticker"] == "NVDA"
    assert result["market"] == "us"


# ── screener-history v1.1 — V3 worker forwards new stage events ──────────────


def test_screen_v3_worker_forwards_new_stage_events(monkeypatch):
    """The V3 pipeline emits ``screen_v3_stage_start / screen_v3_stage_done
    / aggregate_done`` (and the existing ``bundle_progress / guru_unit_done
    / roundtable_*``). The worker MUST forward each event to ``emit_event``
    so the front-end ``ScreenerV3Progress`` cell can advance the timeline.

    Without forwarding, the pipeline events fire but never reach the
    socket — the progress UI would stay frozen even though the backend
    is making progress."""

    captured = []

    # Replace ``emit_event`` BEFORE building the worker — the worker's
    # closure imports the symbol at call time via the module attribute,
    # so monkeypatching the module path is what counts.
    from stock_trading_system.tasks import event_emitter as ee

    def fake_emit(task_id, event, payload, *, db_path=None,
                  user_id=None, socketio=None):
        captured.append({
            "task_id": task_id, "event": event, "payload": payload,
            "user_id": user_id,
        })
        return {"ok": True}

    monkeypatch.setattr(ee, "emit_event", fake_emit)

    # Stub ScreenerV3Pipeline so it fires every event variant the
    # worker is responsible for forwarding. Order mirrors the real
    # pipeline run so a future maintainer reading this test sees the
    # canonical event stream at a glance.
    class FakePipeline:
        def __init__(self, *_, on_progress=None, **_kw):
            self._on_progress = on_progress

        async def run(self, **_kw):
            cb = self._on_progress
            cb({"type": "screen_v3_stage_start", "stage": "parse"})
            cb({"type": "screen_v3_stage_done",  "stage": "parse", "count": 20})
            cb({"type": "bundle_progress", "ticker": "AAPL",
                 "done": 1, "total": 2})
            cb({"type": "screen_v3_stage_start", "stage": "guru", "total": 8})
            cb({"type": "guru_unit_done", "guru": "buffett",
                 "guru_display": "Buffett", "ticker": "AAPL",
                 "progress": 1, "total": 8})
            cb({"type": "screen_v3_stage_done", "stage": "guru", "total": 8})
            cb({"type": "roundtable_start", "tickers": ["AAPL"]})
            cb({"type": "roundtable_done", "ticker": "AAPL",
                 "consensus": ["buffett"], "dissent": [],
                 "progress": 1, "total": 1})
            cb({"type": "screen_v3_stage_done", "stage": "aggregate",
                 "results": 1})
            cb({"type": "aggregate_done", "results_count": 1})
            return {
                "engine": "v3", "mode": "agent_rt",
                "candidates_count": 1, "results": [],
                "metrics": {"duration_sec": 0, "llm_calls": 1},
            }

    monkeypatch.setattr(
        "stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline",
        FakePipeline,
    )

    worker = make_screen_v3_worker()
    progress = []
    result = worker(
        {
            "__task_id__": "test-task-uuid",
            "user_id": 42,
            "provider": "qwen",
            "nl_query": "test", "market": "us",
            "candidate_n": 5, "gurus": ["buffett"], "mode": "agent_rt",
            "with_roundtable": True,
        },
        lambda p, s=None, partial=None: progress.append((p, s)),
    )

    # ``run()`` ran end-to-end.
    assert result["engine"] == "v3"

    # Every event the worker is responsible for must have been emitted.
    forwarded_types = {c["event"] for c in captured}
    required = {
        "screen_v3_stage_start", "screen_v3_stage_done",
        "bundle_progress", "guru_unit_done",
        "roundtable_start", "roundtable_done",
        "aggregate_done",
    }
    missing = required - forwarded_types
    assert not missing, (
        f"V3 worker dropped events: {missing}. "
        f"got: {forwarded_types}"
    )

    # Field plumbing — task_id + user_id flow through every emit so the
    # unified-progress per-user room delivers the event correctly.
    for c in captured:
        assert c["task_id"] == "test-task-uuid"
        assert c["user_id"] == 42

    # Stage start/done payloads carry the ``stage`` field — without it
    # the front-end can't tell which timeline cell to advance.
    stage_evts = [c for c in captured
                  if c["event"] in ("screen_v3_stage_start",
                                     "screen_v3_stage_done")]
    for c in stage_evts:
        assert "stage" in c["payload"], (
            f"stage event missing payload.stage: {c}"
        )


# ── WK-1.4.6 backtest worker ────────────────────────────────────────────────


def test_backtest_worker_success():
    """Backtest worker delegates to BacktestEngine via injected router."""
    import numpy as np
    import pandas as pd

    # Build a fake router whose get_history_for_backtest returns synthetic data
    rng = np.random.default_rng(42)
    days = 120
    closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, days))
    idx = pd.date_range("2025-01-01", periods=days, freq="B")
    df = pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": 1_000_000,
    }, index=idx)

    router = MagicMock()
    router.get_history_for_backtest = MagicMock(return_value=df)

    worker = make_backtest_worker(get_router=lambda: router)
    progress = []
    result = worker(
        {"ticker": "AAPL", "strategy_id": "buy_and_hold",
         "start_date": "2025-01-01", "end_date": "2025-06-01"},
        lambda p, s=None, partial=None: progress.append(p),
    )
    assert result["ticker"] == "AAPL"
    assert result["strategy_id"] == "buy_and_hold"
    assert "total_return" in result["metrics"]
    assert len(result["equity_curve"]) > 0
    # Backtest worker reports at least 3 progress milestones
    assert len(progress) >= 3


def test_backtest_worker_rejects_empty_ticker():
    worker = make_backtest_worker(get_router=lambda: MagicMock())
    with pytest.raises(ValueError, match="ticker"):
        worker({"ticker": ""}, lambda *a, **k: None)


# ── WK-1.4.8 report worker success ───────────────────────────────────────────


def test_report_worker_daily():
    worker = make_report_worker(get_report_gen=lambda: FakeReportGen())
    r = worker({"type": "daily"}, lambda *a, **k: None)
    assert r["type"] == "daily"
    assert r["content"].startswith("# Daily")


def test_report_worker_stock():
    worker = make_report_worker(get_report_gen=lambda: FakeReportGen())
    r = worker({"type": "stock", "ticker": "AAPL"}, lambda *a, **k: None)
    assert "AAPL" in r["content"]


def test_report_worker_stock_missing_ticker():
    worker = make_report_worker(get_report_gen=lambda: FakeReportGen())
    with pytest.raises(ValueError, match="ticker"):
        worker({"type": "stock"}, lambda *a, **k: None)


def test_report_worker_unknown_type():
    worker = make_report_worker(get_report_gen=lambda: FakeReportGen())
    with pytest.raises(ValueError, match="Unknown report type"):
        worker({"type": "yearly"}, lambda *a, **k: None)


# ── WK-1.4.9 qwen fundamentals worker ───────────────────────────────────────


def test_qwen_fundamentals_worker_success():
    router = FakeRouter()
    worker = make_qwen_fundamentals_worker(get_router=lambda: router)
    r = worker({"ticker": "AAPL"}, lambda *a, **k: None)
    assert r["ticker"] == "AAPL"
    assert r["fundamentals"]["pe_ratio"] == 28.5


def test_qwen_fundamentals_no_data_raises():
    router = FakeRouter()
    router.get_fundamentals.return_value = None
    worker = make_qwen_fundamentals_worker(get_router=lambda: router)
    with pytest.raises(ValueError):
        worker({"ticker": "AAPL"}, lambda *a, **k: None)


# ── WK-1.4.10 qwen news worker ───────────────────────────────────────────────


def test_qwen_news_worker_success():
    router = FakeRouter()
    worker = make_qwen_news_worker(get_router=lambda: router)
    r = worker({"ticker": "AAPL", "limit": 5}, lambda *a, **k: None)
    assert r["count"] == 1


# ── echo (smoke) ──────────────────────────────────────────────────────────────


def test_echo_worker():
    r = echo_worker({"hi": "there"}, lambda *a, **k: None)
    assert r["echoed"] == {"hi": "there"}


# ── register_default_workers wires everything end-to-end ─────────────────────


def test_register_default_workers_e2e(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    tm = TaskManager(store, max_workers=2)
    deps = WorkerDeps(
        get_analyzer=lambda: FakeAnalyzer(),
        get_strategy_engine=lambda: FakeStrategyEngine(),
        get_portfolio=lambda: FakePortfolio(),
        get_router=lambda: FakeRouter(),
        get_screener=lambda: FakeScreener(),
        get_report_gen=lambda: FakeReportGen(),
    )
    register_default_workers(tm, deps)
    types = tm.registered_types()
    for required in ("echo", "analysis", "screen", "report",
                     "qwen_fundamentals", "qwen_news", "backtest"):
        assert required in types
    tm.shutdown(wait=True)


def test_register_default_workers_skips_when_deps_missing(tmp_path):
    """Running with only echo + report deps should not crash."""
    store = TaskStore(str(tmp_path / "tasks.db"))
    tm = TaskManager(store, max_workers=1)
    deps = WorkerDeps(get_report_gen=lambda: FakeReportGen())
    register_default_workers(tm, deps)
    types = tm.registered_types()
    assert "echo" in types
    assert "report" in types
    assert "analysis" not in types
    assert "screen" not in types
    tm.shutdown(wait=True)


# ── End-to-end: submit analysis task through TaskManager + workers ───────────


def test_submit_analysis_task_runs_to_completion(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    tm = TaskManager(store, max_workers=1)
    deps = WorkerDeps(
        get_analyzer=lambda: FakeAnalyzer(signal="BUY"),
        get_strategy_engine=lambda: FakeStrategyEngine(),
        get_portfolio=lambda: FakePortfolio(),
        get_router=lambda: FakeRouter(),
    )
    register_default_workers(tm, deps)
    task = tm.submit("analysis", {"ticker": "AAPL"})
    final = tm.wait_for(task["id"], timeout=5)
    assert final["status"] == "success"
    assert final["result_ref"].startswith("analysis_history:")
    result = tm.get_result(task["id"])
    assert result["signal"] == "BUY"
    assert result["ticker"] == "AAPL"
    tm.shutdown(wait=True)
