"""Backtesting engine for rule-based strategies.

This is deliberately lightweight — it replays historical OHLCV bars through a
strategy function, tracks a single-position long-only equity curve, and
returns the run metrics. It is NOT intended to replace a full framework like
backtrader/vectorbt; it exists so the web UI can give users a quick intuition
check for their strategy ideas without adding another heavyweight dependency.

Built-in strategies (no LLM calls — those would make backtesting prohibitive):
- buy_and_hold: baseline. Invest at bar 0, hold until end.
- sma_crossover: golden/death cross on two simple moving averages.
- rsi_mean_reversion: enter long when RSI < 30, exit when RSI > 70.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.utils import get_logger

logger = get_logger("strategy.backtest")


@dataclass
class BacktestTrade:
    """A single round-trip (enter → exit) trade."""
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    shares: float
    pnl: float
    pnl_pct: float
    reason: str = ""


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""
    ticker: str
    strategy: str
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float  # 0.0 - 1.0
    trade_count: int
    equity_curve: list[dict] = field(default_factory=list)  # [{date, equity, price, position}]
    trades: list[BacktestTrade] = field(default_factory=list)
    annualized_return_pct: float = 0.0


# ── Strategy rule functions ────────────────────────────────────────────────
# Each strategy is a function (bar_index, close_series, state, params) → action
# where action is "buy", "sell", or "hold". `state` is a mutable dict the
# strategy can use for its own internal flags.


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI — standard 14-period smoothed variant."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _strategy_buy_and_hold(closes: pd.Series, params: dict) -> pd.Series:
    """Returns an action series: "buy" at bar 0, "hold" elsewhere.

    The engine enforces single-position, so this entry just stays in until end.
    """
    actions = pd.Series(["hold"] * len(closes), index=closes.index)
    if len(actions) > 0:
        actions.iloc[0] = "buy"
    return actions


def _strategy_sma_crossover(closes: pd.Series, params: dict) -> pd.Series:
    short_w = int(params.get("short_window", 20))
    long_w = int(params.get("long_window", 50))
    short_ma = _sma(closes, short_w)
    long_ma = _sma(closes, long_w)
    actions = pd.Series(["hold"] * len(closes), index=closes.index)
    # Detect crossover by comparing sign of (short-long) diff vs previous bar.
    diff = short_ma - long_ma
    prev_diff = diff.shift(1)
    # Golden cross → buy, death cross → sell.
    actions[(prev_diff <= 0) & (diff > 0)] = "buy"
    actions[(prev_diff >= 0) & (diff < 0)] = "sell"
    return actions


def _strategy_rsi_mean_reversion(closes: pd.Series, params: dict) -> pd.Series:
    period = int(params.get("period", 14))
    oversold = float(params.get("oversold", 30))
    overbought = float(params.get("overbought", 70))
    rsi = _rsi(closes, period=period)
    actions = pd.Series(["hold"] * len(closes), index=closes.index)
    actions[rsi < oversold] = "buy"
    actions[rsi > overbought] = "sell"
    return actions


STRATEGIES: dict[str, dict] = {
    "buy_and_hold": {
        "label": "买入并持有",
        "description": "起始日买入，结束日卖出。作为其它策略的基准线。",
        "func": _strategy_buy_and_hold,
        "params": [],
    },
    "sma_crossover": {
        "label": "双均线交叉",
        "description": "短期 SMA 上穿长期 SMA 时买入（金叉），下穿时卖出（死叉）。",
        "func": _strategy_sma_crossover,
        "params": [
            {"name": "short_window", "label": "短周期", "type": "int", "default": 20, "min": 2, "max": 100},
            {"name": "long_window",  "label": "长周期", "type": "int", "default": 50, "min": 5, "max": 250},
        ],
    },
    "rsi_mean_reversion": {
        "label": "RSI 均值回归",
        "description": "RSI 低于超卖线时买入，高于超买线时卖出。",
        "func": _strategy_rsi_mean_reversion,
        "params": [
            {"name": "period",     "label": "RSI 周期", "type": "int",   "default": 14, "min": 2,  "max": 100},
            {"name": "oversold",   "label": "超卖线",   "type": "float", "default": 30, "min": 5,  "max": 50},
            {"name": "overbought", "label": "超买线",   "type": "float", "default": 70, "min": 50, "max": 95},
        ],
    },
}


class Backtester:
    """Runs a single-ticker long-only backtest."""

    def __init__(self, config: dict):
        self._config = config
        self._data = DataManager(config)

    def list_strategies(self) -> list[dict]:
        """Return strategy metadata for the UI (no function references)."""
        return [
            {"id": sid, "label": s["label"], "description": s["description"], "params": s["params"]}
            for sid, s in STRATEGIES.items()
        ]

    def run(
        self,
        ticker: str,
        strategy_id: str,
        initial_capital: float = 100_000.0,
        period: str = "1y",
        params: Optional[dict] = None,
    ) -> BacktestResult:
        """Run the backtest and return a populated BacktestResult.

        Args:
            ticker: Stock symbol.
            strategy_id: One of the keys in STRATEGIES.
            initial_capital: Starting cash.
            period: Historical period for get_history (e.g. "6mo", "1y", "2y").
            params: Strategy-specific parameters (optional — defaults used).
        """
        if strategy_id not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        strat = STRATEGIES[strategy_id]
        params = params or {}

        df = self._data.get_history(ticker, period=period, interval="1d")
        if df is None or len(df) == 0:
            raise ValueError(f"No historical data for {ticker}")

        # Normalise column casing so every downstream path can rely on 'close'.
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        if "close" not in df.columns:
            raise ValueError(f"History for {ticker} missing 'close' column")

        closes = df["close"].astype(float)
        # Compute action signals for every bar in one pass.
        actions = strat["func"](closes, params)

        cash = float(initial_capital)
        shares = 0.0
        entry_price = 0.0
        entry_date = ""
        trades: list[BacktestTrade] = []
        equity_curve: list[dict] = []
        peak_equity = cash
        max_dd = 0.0

        for idx, (ts, row) in enumerate(df.iterrows()):
            price = float(row["close"])
            date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
            action = actions.iloc[idx]

            if action == "buy" and shares == 0 and price > 0:
                # Go all-in (minus 1% slippage) for simplicity.
                shares = (cash * 0.99) / price
                cash -= shares * price
                entry_price = price
                entry_date = date_str
            elif action == "sell" and shares > 0:
                proceeds = shares * price
                pnl = proceeds - (shares * entry_price)
                pnl_pct = ((price / entry_price) - 1) * 100 if entry_price > 0 else 0
                trades.append(BacktestTrade(
                    entry_date=entry_date, entry_price=entry_price,
                    exit_date=date_str, exit_price=price,
                    shares=shares, pnl=pnl, pnl_pct=pnl_pct,
                    reason=f"{strategy_id} exit",
                ))
                cash += proceeds
                shares = 0.0
                entry_price = 0.0
                entry_date = ""

            equity = cash + shares * price
            if equity > peak_equity:
                peak_equity = equity
            dd = ((peak_equity - equity) / peak_equity) * 100 if peak_equity > 0 else 0
            if dd > max_dd:
                max_dd = dd

            equity_curve.append({
                "date": date_str,
                "equity": round(equity, 2),
                "price": round(price, 4),
                "position": round(shares, 4),
            })

        # Force-close any open position at the final bar so returns reflect
        # marked-to-market but also realized P&L.
        if shares > 0 and len(df) > 0:
            last_price = float(df.iloc[-1]["close"])
            last_ts = df.index[-1]
            last_date = last_ts.strftime("%Y-%m-%d") if hasattr(last_ts, "strftime") else str(last_ts)
            pnl = (shares * last_price) - (shares * entry_price)
            pnl_pct = ((last_price / entry_price) - 1) * 100 if entry_price > 0 else 0
            trades.append(BacktestTrade(
                entry_date=entry_date, entry_price=entry_price,
                exit_date=last_date, exit_price=last_price,
                shares=shares, pnl=pnl, pnl_pct=pnl_pct,
                reason="force-close at end",
            ))
            cash += shares * last_price
            shares = 0.0

        final_equity = cash
        total_return_pct = ((final_equity / initial_capital) - 1) * 100 if initial_capital > 0 else 0
        wins = sum(1 for t in trades if t.pnl > 0)
        win_rate = wins / len(trades) if trades else 0.0

        # Rough annualized return — assumes 252 trading days / year and uses
        # the compounded daily growth rate.
        annualized = 0.0
        if len(equity_curve) > 1 and initial_capital > 0:
            days = len(equity_curve)
            growth = final_equity / initial_capital
            if growth > 0:
                annualized = ((growth ** (252 / days)) - 1) * 100

        start_date = equity_curve[0]["date"] if equity_curve else ""
        end_date = equity_curve[-1]["date"] if equity_curve else ""

        return BacktestResult(
            ticker=ticker,
            strategy=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_equity=round(final_equity, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=round(max_dd, 2),
            win_rate=round(win_rate, 4),
            trade_count=len(trades),
            equity_curve=equity_curve,
            trades=trades,
            annualized_return_pct=round(annualized, 2),
        )
