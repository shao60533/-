"""Task-completion hook tests for onboarding v1.0.

4 cases per docs/design/onboarding.md §6.1:

  1. POST /api/portfolio/add success → mark_step("add-holding")
  2. analysis worker success         → mark_step("first-analysis")
  3. screen_v3 worker success        → mark_step("first-screen")
  4. paper-trade plan saved          → mark_step("first-paper-plan")

The hooks are fail-soft (they NEVER raise), so each test asserts the
expected mark_step call landed against a real OnboardingRepository
(populated by the test conftest).
"""

from __future__ import annotations

import sqlite3

import pytest


def _steps_for(db_path: str, user_id: int) -> dict:
    import json
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT steps_completed FROM user_onboarding WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {}
    try:
        steps = json.loads(row[0] or "{}")
        return steps if isinstance(steps, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── 1. portfolio.add ─────────────────────────────────────────────────────
def test_portfolio_add_marks_add_holding(alice_client, app_client):
    rv = alice_client.post(
        "/api/portfolio/add",
        json={"ticker": "AAPL", "shares": 1, "price": 100.0},
    )
    assert rv.status_code == 200, rv.get_json()
    steps = _steps_for(app_client["db_path"], app_client["users"].alice.id)
    assert steps.get("add-holding") is True


# ── 2. analysis worker ───────────────────────────────────────────────────
def test_analysis_worker_marks_first_analysis(app_client):
    """Drive the analysis worker directly so the hook fires without
    spinning up the full TradingAgents pipeline."""
    from stock_trading_system.tasks.workers import make_analysis_worker
    from types import SimpleNamespace

    class _FakeAnalyzer:
        def analyze(self, ticker, date, **kw):
            return SimpleNamespace(
                signal="BUY",
                market_report="m", sentiment_report="s",
                news_report="n", fundamentals_report="f",
                investment_debate="id", risk_assessment="ra",
                trade_decision="td",
                rendering=None,
            )

    class _FakeEngine:
        def derive_advice(self, *a, **kw):
            return None

    def _portfolio():
        return None

    def _router():
        return None

    worker = make_analysis_worker(
        get_analyzer=lambda: _FakeAnalyzer(),
        get_strategy_engine=lambda: _FakeEngine(),
        get_portfolio=_portfolio,
        get_router=_router,
    )

    alice_id = app_client["users"].alice.id

    def _progress_noop(*a, **kw):
        pass

    out = worker(
        {"ticker": "AAPL", "date": "2026-01-15", "__user_id__": alice_id},
        _progress_noop,
    )
    assert isinstance(out, dict)

    steps = _steps_for(app_client["db_path"], alice_id)
    assert steps.get("first-analysis") is True


# ── 3. screen_v3 worker ──────────────────────────────────────────────────
def test_screen_v3_worker_marks_first_screen(app_client, monkeypatch):
    from stock_trading_system.tasks import workers as workers_mod

    # Replace ScreenerV3Pipeline with a tiny fake so we don't need real
    # LLM + market data.
    class _FakePipeline:
        def __init__(self, **kw):
            pass

        async def run(self, **kw):
            return {"ok": True, "candidates": []}

    monkeypatch.setattr(
        "stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline",
        _FakePipeline,
    )

    worker = workers_mod.make_screen_v3_worker()

    alice_id = app_client["users"].alice.id

    def _progress_noop(*a, **kw):
        pass

    out = worker(
        {"user_id": alice_id, "provider": "qwen", "universe": ["AAPL"]},
        _progress_noop,
    )
    assert out["ok"] is True

    steps = _steps_for(app_client["db_path"], alice_id)
    assert steps.get("first-screen") is True


# ── 4. paper-trade plan ──────────────────────────────────────────────────
def test_paper_trade_plan_marks_first_paper_plan(app_client, monkeypatch):
    from stock_trading_system.strategy.paper_trader import event_executor

    alice_id = app_client["users"].alice.id

    class _FakeStore:
        def save_plan(self, **kw):
            return 42

    class _FakeSession(dict):
        pass

    monkeypatch.setattr(
        event_executor, "ensure_ticker_session",
        lambda store, ticker, **kw: _FakeSession(id=1, start_capital=10000.0),
    )
    monkeypatch.setattr(
        event_executor, "extract_plan",
        lambda *a, **kw: ({
            "rating": "BUY",
            "thesis": "test",
            "orders": [],
            "holding_months_min": 6,
            "holding_months_max": 12,
        }, "test"),
    )
    monkeypatch.setattr(
        event_executor.order_engine, "evaluate_day",
        lambda *a, **kw: [],
    )

    result = event_executor.process_analysis(
        _FakeStore(),
        analysis_id=1, ticker="AAPL", analysis_date="2026-01-15",
        signal="BUY",
        advice={"reasoning": "go go go"},
        current_price=150.0, today_bar=None, recent_bars=None,
        qwen_provider=None, analysis_blob=None,
        user_id=alice_id,
    )
    # process_analysis never raises — but the result dict should not flag
    # a fatal error on the hook path.
    assert isinstance(result, dict)

    steps = _steps_for(app_client["db_path"], alice_id)
    assert steps.get("first-paper-plan") is True
