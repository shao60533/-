"""Tests for batch_analysis worker tenant-context handling.

Background: PortfolioManager.get_holdings is multi-tenant strict — calling
it without ``user_id`` raises ``RuntimeError: PortfolioManager: missing
tenant context``. The batch_analysis worker runs in a thread pool, so
there is no Flask ``g.user`` to fall back on; the submitter (``/api/batch/
analyze``) injects ``__user_id__`` into params at submit time. The worker
must surface a clear error when that injection is missing, and must
forward the same id to ``pm.get_holdings`` and to every sub-analysis it
fans out.

Cases:
    1. Happy path — params carry ``__user_id__`` → portfolio fake observes
       the id when ``get_holdings`` is called.
    2. Missing ``__user_id__`` → task fails with an error message
       containing the literal substring ``missing __user_id__``.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_trading_system.tasks.task_manager import TaskManager
from stock_trading_system.tasks.task_store import TaskStore
from stock_trading_system.tasks.workers import (
    WorkerDeps, register_default_workers,
)


# ── Fakes ────────────────────────────────────────────────────────────────────


class _StubAnalyzer:
    def analyze(self, ticker, date, **kwargs):
        return SimpleNamespace(
            signal="HOLD",
            market_report=f"{ticker} market",
            sentiment_report=f"{ticker} sentiment",
            news_report=f"{ticker} news",
            fundamentals_report=f"{ticker} fundamentals",
            investment_debate={"bull": "ok"},
            risk_assessment={"risk": "low"},
            trade_decision={"action": "HOLD"},
        )


class _StubStrategyEngine:
    def generate_advice(self, result, holdings, current_price):
        return SimpleNamespace(
            action="HOLD", confidence="medium",
            suggested_position_pct=5,
            entry_price_low=100, entry_price_high=110,
            stop_loss=95, take_profit=120,
            reasoning="ok", risk_warning=None,
        )


class _SpyPortfolio:
    """Records the ``user_id`` passed to ``get_holdings``."""

    def __init__(self, tickers: list[str]):
        self._tickers = tickers
        self.received_user_ids: list[int | None] = []

    def get_holdings(self, user_id=None):
        self.received_user_ids.append(user_id)
        return [
            {"ticker": t, "shares": 10, "market": "us"}
            for t in self._tickers
        ]


class _StubRouter:
    def __init__(self):
        self.get_price = MagicMock(return_value={"last": 105})
        self.get_fundamentals = MagicMock(return_value={})
        self.get_news = MagicMock(return_value=[])


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def wired_tm(tmp_path):
    db_path = tmp_path / "tasks.db"
    from stock_trading_system.config import load_config, get_config
    load_config()
    cfg = get_config()
    cfg["portfolio"] = {"db_path": str(db_path)}
    store = TaskStore(str(db_path))
    tm = TaskManager(store, max_workers=1)
    return tm, store, str(db_path)


# ── Case 1 — happy path: portfolio fake receives the parent user_id ──────────


def test_batch_analysis_forwards_user_id_to_portfolio(wired_tm):
    tm, _store, _db_path = wired_tm
    spy = _SpyPortfolio(["AAPL", "MSFT"])
    deps = WorkerDeps(
        get_analyzer=lambda: _StubAnalyzer(),
        get_strategy_engine=lambda: _StubStrategyEngine(),
        get_portfolio=lambda: spy,
        get_router=lambda: _StubRouter(),
    )
    register_default_workers(tm, deps)
    try:
        task = tm.submit(
            "batch_analysis",
            {"skip_recent_hours": 0, "__user_id__": 42},
            created_by=42,
        )
        final = tm.wait_for(task["id"], timeout=30)
        assert final["status"] == "success", final

        # ``get_holdings`` is called at least once by the batch worker
        # (line 841). The advice builder for each child analysis also
        # hits ``get_holdings`` via the analysis worker's snapshot path,
        # so the spy may record more than one call — every call must
        # carry the same tenant id, never ``None``.
        assert spy.received_user_ids, "get_holdings was never called"
        assert all(uid == 42 for uid in spy.received_user_ids), (
            spy.received_user_ids
        )
    finally:
        tm.shutdown(wait=True)


# ── Case 2 — missing __user_id__ → task fails with clear error ───────────────


def test_batch_analysis_missing_user_id_fails_with_clear_error(wired_tm):
    tm, _store, _db_path = wired_tm
    spy = _SpyPortfolio(["AAPL"])
    deps = WorkerDeps(
        get_analyzer=lambda: _StubAnalyzer(),
        get_strategy_engine=lambda: _StubStrategyEngine(),
        get_portfolio=lambda: spy,
        get_router=lambda: _StubRouter(),
    )
    register_default_workers(tm, deps)
    try:
        task = tm.submit(
            "batch_analysis",
            {"skip_recent_hours": 0},  # ← no __user_id__
            created_by=42,
        )
        final = tm.wait_for(task["id"], timeout=10)
        assert final["status"] == "failed", final
        err = (final.get("error_message") or "")
        assert "missing __user_id__" in err, err

        # The worker raised before touching PortfolioManager, so the
        # spy never observed a call — guarantees we are NOT leaking a
        # cross-tenant ``get_holdings()`` (no user_id) call into the
        # multi-tenant boundary.
        assert spy.received_user_ids == [], spy.received_user_ids
    finally:
        tm.shutdown(wait=True)
