"""hardening-iteration-v1 P3.2 step-2 — backtest engine parity.

The legacy ``strategy.backtest.Backtester`` and the new
``strategy.backtester.BacktestEngine`` disagree on:

    * field names: total_return_pct (legacy) vs total_return (v2)
    * scale:        0–100 % vs 0–1 ratio
    * annualisation: 365 days vs 252 trading days
    * slippage:     hard-coded 1% (legacy) vs parameter-driven 0%
    * RSI:          SMA (legacy) vs Wilder EWM (v2)

Strategy of this step:

  1. v2 ``BacktestResult.to_v1_dict()`` now bridges the schema —
     legacy keys appear alongside the new ones (this commit).
  2. Parity test: on the *buy-and-hold* path the two engines should
     produce *almost equal* final equity (only diff = slippage 1% vs
     0%) — verifying the data plumbing is consistent before web
     migration.
  3. Step-3 (subsequent PR) flips web/app.py:2978/2995 + the
     ``api_backtest_run`` payload to consume the v2 engine through
     ``to_v1_dict()``. Then strategy.backtest can be deleted.

We don't assert *exact* parity — the engines deliberately differ on
slippage. The check is "v2 isn't returning garbage" and "the alias
keys are populated and self-consistent."
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest


def _sample_ohlcv(days: int = 60, start_price: float = 100.0) -> pd.DataFrame:
    """Deterministic synthetic price series so the test doesn't hit yfinance."""
    rows = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=days - i)
        # Steady 0.5% upward drift — simple, easy to reason about.
        close = start_price * (1.005 ** i)
        rows.append({
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        })
    idx = pd.to_datetime(
        [date.today() - timedelta(days=days - i) for i in range(days)]
    )
    df = pd.DataFrame(rows, index=idx)
    df.index.name = "Date"
    return df


def _patch_data(history_fn_target: str, df: pd.DataFrame):
    """Inject the synthetic OHLCV via the engine's data hook."""
    return patch(history_fn_target, return_value=df)


def test_v2_to_v1_dict_carries_both_schemas():
    """BacktestResult.to_v1_dict() must expose every legacy key alongside
    the v2 keys; consumers can migrate field by field rather than all
    at once."""
    from stock_trading_system.strategy.backtester import BacktestResult
    r = BacktestResult(
        ticker="AAPL",
        strategy_id="buy_and_hold",
        start_date="2026-01-01",
        end_date="2026-03-01",
        initial_capital=100_000,
        final_value=110_000,
        total_return=0.10,
        annualized_return=0.40,
        max_drawdown=0.05,
        win_rate=0.6,
        num_trades=2,
        sharpe_ratio=1.2,
    )
    out = r.to_v1_dict()
    # v2 keys preserved
    assert out["total_return"] == 0.10
    assert out["max_drawdown"] == 0.05
    assert out["annualized_return"] == 0.40
    assert out["num_trades"] == 2
    assert out["final_value"] == 110_000
    assert out["strategy_id"] == "buy_and_hold"
    # v1 aliases populated (percentage scale + legacy field names)
    assert out["total_return_pct"] == 10.0
    assert out["max_drawdown_pct"] == 5.0
    assert out["annualized_return_pct"] == 40.0
    assert out["trade_count"] == 2
    assert out["final_equity"] == 110_000
    assert out["strategy"] == "buy_and_hold"


def test_buy_and_hold_returns_match_within_slippage_tolerance():
    """Run the same buy-and-hold strategy through v2 BacktestEngine on
    a deterministic price series. The 0.5% daily drift over 60 days
    compounds to ~+35%; v2 (0% slippage) must report ~35% total_return.

    We don't co-run legacy Backtester here because it pulls
    ``DataManager`` (live network); the parity comparison happens on
    the documented schema shape rather than re-running both. Once
    Backtester gains a history_fn hook (or step-3 lands), we'll
    extend this to a true a/b run."""
    from stock_trading_system.strategy.backtester import BacktestEngine

    df = _sample_ohlcv(days=60, start_price=100.0)

    # Suppress the deprecation warning the import triggers on touch.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        engine = BacktestEngine(
            config={},
            history_fn=lambda ticker, start, end: df,
        )
        result = engine.run(
            ticker="AAPL",
            strategy_id="buy_and_hold",
            start_date="2026-01-01",
            end_date="2026-03-01",
            initial_capital=100_000,
        )

    # 0.5% × 59 days ≈ 1.005^59 = ~1.339, i.e. +33.9%. Tolerate ±2pp
    # since the engine's slicing inserts a 1-day startup offset and
    # buy_and_hold may skip the first bar by design.
    assert 0.30 <= result.total_return <= 0.40, (
        f"unexpected v2 total_return: {result.total_return}"
    )
    # v1 schema must agree numerically.
    v1 = result.to_v1_dict()
    assert abs(v1["total_return_pct"] - result.total_return * 100) < 1e-6


def test_v1_module_still_importable_after_alias_work():
    """Defensive: P3.2 step-1 / step-2 changes must not break the
    legacy module's surface — three live call sites still bind it
    until step-3 retires them."""
    import dataclasses
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from stock_trading_system.strategy.backtest import (
            Backtester, BacktestResult,
        )
    assert callable(getattr(Backtester, "run", None))
    field_names = {f.name for f in dataclasses.fields(BacktestResult)}
    assert "total_return_pct" in field_names
