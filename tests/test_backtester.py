"""Backtest engine tests — BT-6.1.*, BM-6.2.*, BD-6.3.*

Uses a synthetic OHLCV DataFrame fed via injected history_fn so the
tests are deterministic and don't hit yfinance.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from stock_trading_system.strategy.backtester import (
    STRATEGIES, BacktestEngine, BacktestResult, make_router_history_fn,
)


# ── Synthetic data generators ────────────────────────────────────────────────


def _trending_up(days=300, start_price=100, daily_drift=0.002, seed=42):
    """Generates a synthetic upward-drifting OHLCV series."""
    rng = np.random.default_rng(seed)
    daily_returns = rng.normal(daily_drift, 0.01, days)
    closes = start_price * np.cumprod(1 + daily_returns)
    opens = np.concatenate(([start_price], closes[:-1]))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.005, days)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.005, days)))
    volumes = rng.integers(1_000_000, 5_000_000, days)
    idx = pd.date_range("2025-01-01", periods=days, freq="B")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=idx)


def _flat(days=200, price=100):
    idx = pd.date_range("2025-01-01", periods=days, freq="B")
    return pd.DataFrame({
        "open": [price] * days, "high": [price * 1.001] * days,
        "low": [price * 0.999] * days, "close": [price] * days,
        "volume": [1_000_000] * days,
    }, index=idx)


def _engine_with_data(df):
    """Build an engine whose history_fn returns the provided DataFrame."""
    return BacktestEngine(config={}, history_fn=lambda t, s, e: df)


# ── BT-6.1.1 SMA crossover ───────────────────────────────────────────────────


def test_sma_crossover_runs_to_completion():
    df = _trending_up(days=300)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="AAPL", strategy_id="sma_crossover",
        start_date="2025-01-01", end_date="2026-03-01",
        initial_capital=100_000,
        params={"short_period": 20, "long_period": 50},
    )
    assert isinstance(result, BacktestResult)
    assert result.ticker == "AAPL"
    assert result.strategy_id == "sma_crossover"
    assert result.initial_capital == 100_000
    assert len(result.equity_curve) == len(df)
    # Benchmark curve attached for non-buy-hold strategies
    assert len(result.benchmark_curve) == len(df)


# ── BT-6.1.2 RSI mean reversion ──────────────────────────────────────────────


def test_rsi_mean_reversion_runs_to_completion():
    """v1.7 — canonical id is ``rsi_mean_reversion``. Strategy result
    surfaces the canonical id even when callers pass it directly."""
    df = _trending_up(days=200)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="MSFT", strategy_id="rsi_mean_reversion",
        start_date="2025-01-01", end_date="2025-10-01",
        initial_capital=50_000,
        params={"period": 14, "oversold": 30, "overbought": 70},
    )
    assert result.strategy_id == "rsi_mean_reversion"
    assert result.equity_curve  # at least non-empty


def test_rsi_reversal_legacy_id_resolves_to_canonical():
    """A stale frontend or a stored ``backtest_results`` row that uses
    the legacy ``rsi_reversal`` id must still execute and surface the
    canonical id on the result."""
    df = _trending_up(days=200)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="MSFT", strategy_id="rsi_reversal",       # legacy alias
        start_date="2025-01-01", end_date="2025-10-01",
        initial_capital=50_000,
    )
    assert result.strategy_id == "rsi_mean_reversion"  # canonical id
    assert result.equity_curve


# ── BT-6.1.3 buy-and-hold has exactly 1 entry ────────────────────────────────


def test_buy_and_hold_one_entry_no_exit():
    df = _trending_up(days=100, daily_drift=0.001)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="AAPL", strategy_id="buy_and_hold",
        start_date="2025-01-01", end_date="2025-06-01",
        initial_capital=100_000,
    )
    buy_actions = [t for t in result.trades if t["action"] == "BUY"]
    sell_actions = [t for t in result.trades if t["action"] == "SELL"]
    assert len(buy_actions) == 1
    assert len(sell_actions) == 0
    # Buy-and-hold has no benchmark attached (it IS the benchmark)
    assert result.benchmark_curve == []


# ── BT-6.1.4 strategies list API ─────────────────────────────────────────────


def test_list_strategies_returns_three_with_required_fields():
    """v1.7 — canonical RSI id is ``rsi_mean_reversion``. Each entry
    must expose ``id`` / ``name`` / ``description`` / ``params``; the
    ``label`` alias is also required for one-release migration so the
    React frontend can read ``s.name ?? s.label ?? s.id`` without
    blowing up against either shape."""
    engine = BacktestEngine(config={})
    strategies = engine.list_strategies()
    assert len(strategies) == 3
    ids = {s["id"] for s in strategies}
    assert ids == {"sma_crossover", "rsi_mean_reversion", "buy_and_hold"}, (
        f"strategy ids must be canonical (got {ids}). The old "
        f"``rsi_reversal`` is the worker-engine legacy alias and must "
        f"NOT appear in the registry — only resolved via canonical_strategy_id."
    )
    for s in strategies:
        assert "name" in s
        assert "label" in s, f"strategy {s['id']} missing ``label`` alias"
        assert "description" in s
        assert "params" in s


# ── BM-6.2.1 total return correctness for buy-and-hold ──────────────────────


def test_total_return_matches_underlying_for_buy_and_hold():
    df = _trending_up(days=100, daily_drift=0.001, seed=1)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="X", strategy_id="buy_and_hold",
        start_date="2025-01-01", end_date="2025-06-01",
        initial_capital=100_000,
    )
    # With buy-and-hold, return ≈ price change minus rounding from int shares.
    expected_pct = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0]
    # Allow 1% tolerance for integer-share quantization
    assert abs(result.total_return - expected_pct) < 0.01


# ── BM-6.2.2 max drawdown is non-negative and bounded by 1 ──────────────────


def test_max_drawdown_in_valid_range():
    df = _trending_up(days=200, seed=7)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="X", strategy_id="sma_crossover",
        start_date="2025-01-01", end_date="2025-09-01",
        initial_capital=100_000,
    )
    assert 0 <= result.max_drawdown <= 1


# ── BM-6.2.3 win rate is a fraction in [0, 1] ───────────────────────────────


def test_win_rate_bounded():
    df = _trending_up(days=300, seed=11)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="X", strategy_id="sma_crossover",
        start_date="2025-01-01", end_date="2026-03-01",
        initial_capital=100_000,
    )
    assert 0 <= result.win_rate <= 1


# ── BM-6.2.4 annualized return scales by trading days ───────────────────────


def test_annualized_return_finite_when_total_return_known():
    df = _trending_up(days=252, seed=3)  # ~1 trading year
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="X", strategy_id="buy_and_hold",
        start_date="2025-01-01", end_date="2026-01-01",
        initial_capital=100_000,
    )
    # For ~1 year span, annualized ≈ total_return
    assert abs(result.annualized_return - result.total_return) < 0.05


# ── BM-6.2.5 num_trades matches sell count ───────────────────────────────────


def test_num_trades_equals_sell_count():
    df = _trending_up(days=300, seed=21)
    engine = _engine_with_data(df)
    result = engine.run(
        ticker="X", strategy_id="sma_crossover",
        start_date="2025-01-01", end_date="2026-03-01",
        initial_capital=100_000,
    )
    sells = [t for t in result.trades if t["action"] == "SELL"]
    assert result.num_trades == len(sells)


# ── BD-6.3.1 first run hits history_fn ───────────────────────────────────────


def test_first_run_calls_history_fn(monkeypatch):
    df = _trending_up(days=100)
    history_fn = MagicMock(return_value=df)
    engine = BacktestEngine(config={}, history_fn=history_fn)
    engine.run(ticker="AAPL", strategy_id="buy_and_hold",
               start_date="2025-01-01", end_date="2025-06-01")
    history_fn.assert_called_once()


# ── BD-6.3.2 router-backed history_fn benefits from cache ───────────────────


def test_router_history_fn_uses_cache(tmp_path):
    """Same ticker+period twice → only one underlying yfinance call."""
    from stock_trading_system.data.local_cache import LocalCache
    from stock_trading_system.data.data_router import DataRouter

    df = _trending_up(days=100)
    yf_mock = MagicMock()
    yf_mock.get_stock_history = MagicMock(return_value=df)

    cache = LocalCache(str(tmp_path / "cache.db"))
    router = DataRouter(
        config={"data_routing": {"primary": "qwen", "enable_cache": True}},
        yfinance=yf_mock, cache=cache,
    )
    history_fn = make_router_history_fn(router)
    engine = BacktestEngine(config={}, history_fn=history_fn)

    engine.run("AAPL", "buy_and_hold", "2025-01-01", "2025-06-01")
    engine.run("AAPL", "buy_and_hold", "2025-01-01", "2025-06-01")

    # yfinance.get_stock_history hit only once thanks to LocalCache hit
    assert yf_mock.get_stock_history.call_count == 1


# ── BD-6.3.4 backtest does NOT touch Qwen ────────────────────────────────────


def test_backtest_never_calls_qwen(tmp_path):
    from stock_trading_system.data.local_cache import LocalCache
    from stock_trading_system.data.data_router import DataRouter

    df = _trending_up(days=80)
    qwen_mock = MagicMock()
    qwen_mock.enabled = True
    yf_mock = MagicMock()
    yf_mock.get_stock_history = MagicMock(return_value=df)

    router = DataRouter(
        config={"data_routing": {"primary": "qwen", "enable_cache": True}},
        qwen=qwen_mock, yfinance=yf_mock,
        cache=LocalCache(str(tmp_path / "cache.db")),
    )
    engine = BacktestEngine(config={}, history_fn=make_router_history_fn(router))
    engine.run("AAPL", "buy_and_hold", "2025-01-01", "2025-04-01")

    # Backtest must not invoke Qwen for any reason.
    qwen_mock.get_stock_price.assert_not_called()
    qwen_mock.get_fundamentals.assert_not_called()
    qwen_mock.get_news.assert_not_called()


# ── BD-6.3.5 insufficient data raises ────────────────────────────────────────


def test_too_few_data_points_raises():
    df = _trending_up(days=3)
    engine = _engine_with_data(df)
    with pytest.raises(ValueError, match="Insufficient data"):
        engine.run("AAPL", "sma_crossover", "2025-01-01", "2025-01-10")


# ── BD-6.3.6 history_fn returns None → raises ────────────────────────────────


def test_no_data_available_raises():
    engine = BacktestEngine(config={}, history_fn=lambda t, s, e: None)
    with pytest.raises(ValueError, match="Insufficient data"):
        engine.run("ZZZZ", "buy_and_hold", "2025-01-01", "2025-06-01")


# ── Unknown strategy id ──────────────────────────────────────────────────────


def test_unknown_strategy_raises():
    df = _trending_up(days=50)
    engine = _engine_with_data(df)
    with pytest.raises(ValueError, match="Unknown strategy"):
        engine.run("AAPL", "made_up_strategy", "2025-01-01", "2025-03-01")


# ── make_router_history_fn period bucketing ──────────────────────────────────


def test_router_history_fn_bucket_short_span():
    router = MagicMock()
    df = _trending_up(days=20)
    router.get_history_for_backtest = MagicMock(return_value=df)
    fn = make_router_history_fn(router)
    fn("AAPL", "2025-01-01", "2025-01-15")  # 14 days
    args, kwargs = router.get_history_for_backtest.call_args
    assert kwargs.get("period") == "1mo"


def test_router_history_fn_bucket_long_span():
    router = MagicMock()
    df = _trending_up(days=200)
    router.get_history_for_backtest = MagicMock(return_value=df)
    fn = make_router_history_fn(router)
    fn("AAPL", "2020-01-01", "2030-01-01")  # ~10 years
    args, kwargs = router.get_history_for_backtest.call_args
    assert kwargs.get("period") == "10y"


# ── Equity curve always non-empty for valid run ──────────────────────────────


def test_equity_curve_length_matches_data():
    df = _flat(days=150, price=100)  # flat → no signals trigger SMA
    engine = _engine_with_data(df)
    result = engine.run("X", "buy_and_hold", "2025-01-01", "2025-08-01",
                        initial_capital=10_000)
    assert len(result.equity_curve) == 150
    # Every point has the required keys
    assert all("date" in p and "value" in p for p in result.equity_curve)
