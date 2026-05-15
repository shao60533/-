"""Tests for the batch_analysis → analysis_history fan-out fix.

Background bug (pre-fix): batch_analysis used to stash the full result
as a JSON blob via task_store._save_generic_result, so per-ticker
sub-analyses never appeared in /api/history and never triggered the
user_analysis_advice / paper_trade / agent_score post-save hooks.

The fix lives in TaskManager.record_child_analysis: the batch worker
now persists each successful ticker as its own analysis_history row
with a synthetic task_id ``batch:{parent}:{ticker}:{index}`` and fires
the same post-save hook chain the single-ticker /api/analyze flow uses.

Test surface (4 cases, per spec §12):

    1. Two successful tickers → 2 new analysis_history rows + 2
       valid analysis_id values in the batch ``items`` array.
    2. One success + one failure → exactly 1 analysis_history row
       written; the failed ticker shows up in items with ``status =
       failed`` but never touches the table.
    3. A skipped ticker (recently analysed) reuses ``last_analysis_id``
       and does NOT mint a new analysis_history row.
    4. Single-ticker /api/analyze flow still writes exactly 1 row —
       regression guard so we never double-save or skip the
       canonical path.

These complement (not replace) the route-level coverage in
tests/web/test_api_batch_analyze.py which guards the HTTP surface.
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


# ── Fakes ──────────────────────────────────────────────────────────────────
#
# Kept minimal — the worker just needs an analyzer that returns the
# canonical report-shaped namespace, a strategy engine that emits a
# valid advice, a portfolio that lists the ticker set, and a router
# that satisfies the price-lookup contracts the paper-trade hook
# tries (but fails gracefully on) to use.


class _ProgrammableAnalyzer:
    """FakeAnalyzer where you can pick which tickers throw.

    The batch worker swallows per-ticker exceptions and records them as
    ``items[i].status = "failed"`` — we use this to drive case 2 + 4.
    """

    def __init__(self, fail_tickers: set[str] | None = None,
                 signal: str = "BUY"):
        self._fail = set(fail_tickers or [])
        self._signal = signal

    def analyze(self, ticker, date, **kwargs):
        if ticker in self._fail:
            raise RuntimeError(f"synthetic analyzer failure for {ticker}")
        return SimpleNamespace(
            signal=self._signal,
            market_report=f"{ticker} market ok",
            sentiment_report=f"{ticker} sentiment",
            news_report=f"{ticker} news",
            fundamentals_report=f"{ticker} fundamentals",
            investment_debate={"bull": "ok", "bear": "ok"},
            risk_assessment={"risk": "low"},
            trade_decision={"action": "BUY"},
        )


class _FakeStrategyEngine:
    def generate_advice(self, result, holdings, current_price):
        return SimpleNamespace(
            action="BUY", confidence="high",
            suggested_position_pct=10,
            entry_price_low=145, entry_price_high=155,
            stop_loss=140, take_profit=170,
            reasoning="ok", risk_warning=None,
        )


class _FakeMultiPortfolio:
    def __init__(self, tickers: list[str]):
        self._tickers = tickers

    def get_holdings(self, user_id=None):
        # batch worker ignores user_id (calls without it); we accept the
        # kw for forward-compat with the explicit-user pattern.
        return [{"ticker": t, "shares": 10, "market": "us"}
                for t in self._tickers]


class _FakeRouter:
    def __init__(self):
        self.get_price = MagicMock(return_value={"last": 150})
        self.get_fundamentals = MagicMock(return_value={
            "ticker": "X", "pe_ratio": 20.0, "market_cap": 1e11,
            "pb_ratio": 5.0, "eps": 4.0,
        })
        self.get_news = MagicMock(return_value=[])


@pytest.fixture
def configured_tm(tmp_path, monkeypatch):
    """Build a TaskManager + WorkerDeps wired against an isolated tmp db.

    Pins ``portfolio.db_path`` via the config singleton so the post-save
    hook (user_analysis_advice / paper_trade) writes to the same db
    file as TaskStore — keeps the dev portfolio.db pristine.
    """
    db_path = tmp_path / "tasks.db"
    from stock_trading_system.config import load_config, get_config
    load_config()
    cfg = get_config()
    cfg["portfolio"] = {"db_path": str(db_path)}

    store = TaskStore(str(db_path))
    tm = TaskManager(store, max_workers=1)
    return tm, store, str(db_path)


def _count_analysis_history(db_path: str, ticker: str | None = None) -> int:
    with sqlite3.connect(db_path) as conn:
        if ticker:
            row = conn.execute(
                "SELECT COUNT(*) FROM analysis_history WHERE ticker=?",
                (ticker,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM analysis_history"
            ).fetchone()
        return row[0]


# ── Case 1 — two successful tickers → 2 history rows ─────────────────────


def test_batch_two_successes_creates_two_analysis_history_rows(configured_tm):
    tm, store, db_path = configured_tm
    deps = WorkerDeps(
        get_analyzer=lambda: _ProgrammableAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakeMultiPortfolio(["AAPL", "MSFT"]),
        get_router=lambda: _FakeRouter(),
    )
    register_default_workers(tm, deps)
    try:
        # skip_recent_hours=0 disables the dedup window so both tickers
        # really run analysis — the case-3 test is where we exercise the
        # skip branch.
        task = tm.submit("batch_analysis",
                         {"skip_recent_hours": 0, "__user_id__": 1})
        final = tm.wait_for(task["id"], timeout=10)
        assert final["status"] == "success", final

        # Two child analysis_history rows: one AAPL, one MSFT.
        assert _count_analysis_history(db_path) == 2
        assert _count_analysis_history(db_path, "AAPL") == 1
        assert _count_analysis_history(db_path, "MSFT") == 1

        # The batch result envelope carries the same analysis_id values.
        batch_result = tm.get_result(task["id"])
        items = batch_result.get("items") or []
        assert len(items) == 2
        for it in items:
            assert it["status"] == "success", it
            assert isinstance(it["analysis_id"], int), it
            assert it["analysis_id"] > 0

        # Synthetic child task_ids must NOT collide with the parent.
        with sqlite3.connect(db_path) as conn:
            task_ids = [r[0] for r in conn.execute(
                "SELECT task_id FROM analysis_history",
            ).fetchall()]
        assert all(tid.startswith(f"batch:{task['id']}:") for tid in task_ids), task_ids
        assert len(set(task_ids)) == 2  # both ids unique
    finally:
        tm.shutdown(wait=True)


# ── Case 2 — one success + one failure → exactly 1 history row ───────────


def test_batch_one_success_one_failure_writes_exactly_one_row(configured_tm):
    tm, store, db_path = configured_tm
    deps = WorkerDeps(
        get_analyzer=lambda: _ProgrammableAnalyzer(fail_tickers={"BADCO"}),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakeMultiPortfolio(["AAPL", "BADCO"]),
        get_router=lambda: _FakeRouter(),
    )
    register_default_workers(tm, deps)
    try:
        task = tm.submit("batch_analysis",
                         {"skip_recent_hours": 0, "__user_id__": 1})
        final = tm.wait_for(task["id"], timeout=10)
        assert final["status"] == "success", final

        # Exactly one analysis_history row (AAPL), none for BADCO.
        assert _count_analysis_history(db_path) == 1
        assert _count_analysis_history(db_path, "AAPL") == 1
        assert _count_analysis_history(db_path, "BADCO") == 0

        batch_result = tm.get_result(task["id"])
        assert batch_result["succeeded"] == 1
        assert batch_result["failed"] == 1
        items_by_status = {it["status"]: it for it in batch_result["items"]}
        assert "success" in items_by_status
        assert "failed" in items_by_status
        assert items_by_status["success"]["ticker"] == "AAPL"
        assert items_by_status["success"]["analysis_id"] is not None
        assert items_by_status["failed"]["ticker"] == "BADCO"
        # Failed items carry an error message; analysis_id absent.
        assert "error" in items_by_status["failed"]
        assert "analysis_id" not in items_by_status["failed"]
    finally:
        tm.shutdown(wait=True)


# ── Case 3 — skipped ticker (recently analysed) does NOT add a new row ──


def test_batch_skipped_ticker_keeps_last_analysis_id_no_new_row(configured_tm):
    tm, store, db_path = configured_tm
    deps = WorkerDeps(
        get_analyzer=lambda: _ProgrammableAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakeMultiPortfolio(["AAPL"]),
        get_router=lambda: _FakeRouter(),
    )
    register_default_workers(tm, deps)
    try:
        # 1. Seed: run a batch once so AAPL has a fresh analysis_history row.
        first = tm.submit("batch_analysis",
                          {"skip_recent_hours": 0, "__user_id__": 1})
        tm.wait_for(first["id"], timeout=10)
        assert _count_analysis_history(db_path, "AAPL") == 1

        # 2. Re-run with skip_recent_hours=24. AAPL should now be skipped.
        second = tm.submit("batch_analysis",
                           {"skip_recent_hours": 24, "__user_id__": 1})
        final = tm.wait_for(second["id"], timeout=10)
        assert final["status"] == "success", final

        # No new row created — still exactly 1 row total.
        assert _count_analysis_history(db_path, "AAPL") == 1

        batch_result = tm.get_result(second["id"])
        assert batch_result["skipped"] == 1
        assert batch_result["succeeded"] == 0
        skipped_item = batch_result["items"][0]
        assert skipped_item["status"] == "skipped"
        # last_analysis_id points at the row from step 1.
        assert isinstance(skipped_item["last_analysis_id"], int)
        assert skipped_item["last_analysis_id"] > 0
    finally:
        tm.shutdown(wait=True)


# ── Case 4 — single-ticker /api/analyze flow still writes exactly 1 row ──


def test_single_analysis_path_writes_exactly_one_row_no_regression(configured_tm):
    """Guard: the fix must not double-save the single-ticker path.

    A regression here would mean either the post-save hook fires twice
    (creating a duplicate row) or the worker started carrying
    record_child_analysis side effects into the normal path.
    """
    tm, store, db_path = configured_tm
    deps = WorkerDeps(
        get_analyzer=lambda: _ProgrammableAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakeMultiPortfolio([]),
        get_router=lambda: _FakeRouter(),
    )
    register_default_workers(tm, deps)
    try:
        task = tm.submit("analysis",
                         {"ticker": "AAPL", "date": "2026-05-15",
                          "__user_id__": 1})
        final = tm.wait_for(task["id"], timeout=10)
        assert final["status"] == "success", final
        assert final["result_ref"].startswith("analysis_history:")

        assert _count_analysis_history(db_path, "AAPL") == 1
        # The single-ticker row points at the *real* task id, not a
        # synthetic batch-child id.
        with sqlite3.connect(db_path) as conn:
            tid = conn.execute(
                "SELECT task_id FROM analysis_history WHERE ticker=?",
                ("AAPL",),
            ).fetchone()[0]
        assert tid == task["id"]
        assert not tid.startswith("batch:")
    finally:
        tm.shutdown(wait=True)
