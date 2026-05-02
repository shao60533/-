"""Strategy backtesting engine with built-in trading strategies.

Runs historical simulations of trading strategies against OHLCV data
to evaluate performance metrics like returns, drawdown, and win rate.

Data sourcing:
- By default uses yfinance directly (see _default_history_fn).
- Production: pass a `history_fn` that wraps DataRouter so results are
  cached in LocalCache (see ARCHITECTURE_UPGRADE_PROPOSAL §4.8).
- Qwen is intentionally NOT used for backtest data — see §4.4.3.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("strategy.backtest")


# Type for a history function: (ticker, start, end) -> DataFrame | None.
HistoryFn = Callable[[str, str, str], "pd.DataFrame | None"]


def _default_history_fn(ticker: str, start: str, end: str) -> "pd.DataFrame | None":
    """Fetch OHLCV via yfinance directly (no cache).

    Used when no router-backed history function is injected. Production
    callers should inject a router-backed function for caching benefit.
    """
    try:
        import yfinance as yf
        data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data.columns = [str(c).lower() for c in data.columns]
        return data
    except Exception as e:
        logger.error("Default history fetch failed for %s: %s", ticker, e)
        return None


def make_router_history_fn(router) -> HistoryFn:
    """Build a history function that pulls through DataRouter (cached).

    DataRouter's get_history_for_backtest expects a `period` (e.g. '1y')
    plus interval; here we map start_date/end_date → an approximate period
    so the call still benefits from cache. Period selection is conservative
    (rounds up) to ensure all requested days are covered.
    """
    def fn(ticker: str, start: str, end: str) -> "pd.DataFrame | None":
        try:
            sdt = pd.Timestamp(start)
            edt = pd.Timestamp(end)
            days = max((edt - sdt).days, 1)
        except Exception:
            days = 365
        # Map total span to a yfinance-compatible period bucket.
        if days <= 5:
            period = "5d"
        elif days <= 30:
            period = "1mo"
        elif days <= 90:
            period = "3mo"
        elif days <= 180:
            period = "6mo"
        elif days <= 365:
            period = "1y"
        elif days <= 730:
            period = "2y"
        elif days <= 1825:
            period = "5y"
        else:
            period = "10y"
        df = router.get_history_for_backtest(
            ticker, period=period, interval="1d",
        )
        if df is None or len(df) == 0:
            return None
        # Normalize column names to lowercase for consistency
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        # Slice to requested window where possible
        try:
            df = df.loc[start:end]
        except Exception:
            pass
        return df
    return fn


@dataclass
class BacktestResult:
    """Result of a strategy backtest."""
    ticker: str
    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    sharpe_ratio: float = 0.0
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    benchmark_curve: list = field(default_factory=list)


# v1.7 — single source of truth for strategy registry. The previous
# split (this list + a separate dict in ``strategy/backtest.py`` with
# different ids — ``rsi_reversal`` vs ``rsi_mean_reversion`` — and a
# different label key — ``label`` vs ``name``) led to UI rows that
# silently fell back to ``buy_and_hold`` when the user picked an
# RSI strategy. ``Backtester`` (the sync-API class) and the worker
# both read from this registry now via ``BacktestEngine.list_strategies()``.
#
# Each entry exposes BOTH ``name`` (the canonical label going forward)
# and ``label`` (alias for the older sync-API consumers). The frontend
# reads ``name ?? label ?? id`` so either side works during migration.
STRATEGIES = [
    {
        "id": "sma_crossover",
        "name": "双均线交叉",
        "label": "双均线交叉",
        "description": "短期 SMA 上穿长期 SMA 时买入（金叉），下穿时卖出（死叉）。",
        "params": [
            {"name": "short_period", "label": "短期均线", "default": 10, "type": "int"},
            {"name": "long_period", "label": "长期均线", "default": 30, "type": "int"},
        ],
    },
    {
        # v1.7 — id is ``rsi_mean_reversion`` (was ``rsi_reversal``).
        # Drift between the two engines silently routed the worker
        # to ``buy_and_hold`` when the user picked RSI. Old rows
        # in ``backtest_results`` keep their stored id; the engine
        # accepts the legacy alias below for one-release migration.
        "id": "rsi_mean_reversion",
        "name": "RSI 均值回归",
        "label": "RSI 均值回归",
        "description": "RSI 低于超卖线时买入，高于超买线时卖出。",
        "params": [
            {"name": "period", "label": "RSI 周期", "default": 14, "type": "int"},
            {"name": "oversold", "label": "超卖线", "default": 30, "type": "int"},
            {"name": "overbought", "label": "超买线", "default": 70, "type": "int"},
        ],
    },
    {
        "id": "buy_and_hold",
        "name": "买入并持有（基线）",
        "label": "买入并持有（基线）",
        "description": "起始日买入，结束日卖出。作为其它策略的基准线。",
        "params": [],
    },
]

# Legacy ID aliases — accept old form, redirect to canonical id. Kept
# so a stale frontend or a ``backtest_results`` row with the old id
# still resolves to a known strategy.
STRATEGY_ID_ALIASES: dict[str, str] = {
    "rsi_reversal": "rsi_mean_reversion",
}


def canonical_strategy_id(strategy_id: str) -> str:
    """Resolve any caller-supplied id to the canonical registry id.
    Returns the input unchanged when no alias matches."""
    return STRATEGY_ID_ALIASES.get(strategy_id, strategy_id)


class BacktestEngine:
    """Run strategy backtests against historical data.

    Args:
        config: System config (unused at runtime today, kept for API stability).
        history_fn: Optional callable (ticker, start, end) → DataFrame.
            Falls back to direct yfinance download. Inject the router-backed
            function (`make_router_history_fn`) in production for caching.
    """

    def __init__(self, config: dict, history_fn: HistoryFn | None = None):
        self._config = config
        self._history_fn = history_fn or _default_history_fn

    def list_strategies(self) -> list[dict]:
        return STRATEGIES

    def run(
        self,
        ticker: str,
        strategy_id: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000,
        params: dict | None = None,
    ) -> BacktestResult:
        """Execute a backtest.

        Args:
            ticker: Stock symbol
            strategy_id: One of sma_crossover, rsi_reversal, buy_and_hold
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD
            initial_capital: Starting capital
            params: Strategy-specific parameters

        Returns:
            BacktestResult with metrics, equity curve, and trade log
        """
        params = params or {}
        # Resolve legacy ids (``rsi_reversal`` → ``rsi_mean_reversion``)
        # so callers / stored rows that predate the canonical-id rename
        # still dispatch correctly.
        strategy_id = canonical_strategy_id(strategy_id)
        logger.info("Backtest %s on %s: %s → %s ($%s)", strategy_id, ticker, start_date, end_date, initial_capital)

        # Fetch historical data
        df = self._get_data(ticker, start_date, end_date)
        if df is None or len(df) < 5:
            raise ValueError(f"Insufficient data for {ticker} ({start_date} to {end_date})")

        # Generate signals
        if strategy_id == "sma_crossover":
            signals = self._sma_crossover(df, **params)
        elif strategy_id == "rsi_mean_reversion":
            signals = self._rsi_reversal(df, **params)
        elif strategy_id == "buy_and_hold":
            signals = self._buy_and_hold(df)
        else:
            raise ValueError(f"Unknown strategy: {strategy_id}")

        # Simulate trades
        result = self._simulate(ticker, strategy_id, df, signals, initial_capital, start_date, end_date)

        # Add buy-and-hold benchmark curve
        if strategy_id != "buy_and_hold":
            bh_signals = self._buy_and_hold(df)
            bh_result = self._simulate(ticker, "buy_and_hold", df, bh_signals, initial_capital, start_date, end_date)
            result.benchmark_curve = bh_result.equity_curve

        logger.info("Backtest complete: return=%.2f%%, trades=%d", result.total_return * 100, result.num_trades)
        return result

    def _get_data(self, ticker: str, start: str, end: str) -> pd.DataFrame | None:
        """Fetch OHLCV via the configured history function."""
        try:
            return self._history_fn(ticker, start, end)
        except Exception as e:  # noqa: BLE001
            logger.error("History fetch failed for %s: %s", ticker, e)
            return None

    # ── Strategies ──────────────────────────────────────────────────────

    def _sma_crossover(self, df: pd.DataFrame, short_period: int = 10, long_period: int = 30, **_) -> pd.Series:
        """SMA crossover: buy when short > long, sell when short < long."""
        short_ma = df["close"].rolling(short_period).mean()
        long_ma = df["close"].rolling(long_period).mean()
        signal = pd.Series(0, index=df.index)
        signal[short_ma > long_ma] = 1   # Buy signal
        signal[short_ma <= long_ma] = -1  # Sell signal
        return signal

    def _rsi_reversal(self, df: pd.DataFrame, period: int = 14, oversold: int = 30, overbought: int = 70, **_) -> pd.Series:
        """RSI mean reversion: buy when oversold, sell when overbought."""
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        signal = pd.Series(0, index=df.index)
        signal[rsi < oversold] = 1    # Buy
        signal[rsi > overbought] = -1  # Sell
        return signal

    def _buy_and_hold(self, df: pd.DataFrame, **_) -> pd.Series:
        """Buy on first day, hold forever."""
        signal = pd.Series(1, index=df.index)
        return signal

    # ── Simulation Engine ───────────────────────────────────────────────

    def _simulate(
        self, ticker: str, strategy_id: str, df: pd.DataFrame,
        signals: pd.Series, capital: float, start_date: str, end_date: str,
    ) -> BacktestResult:
        """Simulate trades based on signals and compute metrics."""
        cash = capital
        shares = 0
        equity_curve = []
        trades = []
        entry_price = 0.0
        entry_date = None

        for i, (date, row) in enumerate(df.iterrows()):
            price = row["close"]
            sig = signals.iloc[i]
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)

            # Buy signal: go all-in if not already holding
            if sig == 1 and shares == 0:
                shares = int(cash / price)
                if shares > 0:
                    cost = shares * price
                    cash -= cost
                    entry_price = price
                    entry_date = date_str
                    trades.append({
                        "date": date_str, "action": "BUY", "price": round(price, 2),
                        "shares": shares, "value": round(cost, 2),
                    })

            # Sell signal: sell all if holding
            elif sig == -1 and shares > 0:
                proceeds = shares * price
                pnl = (price - entry_price) * shares
                hold_days = (pd.Timestamp(date_str) - pd.Timestamp(entry_date)).days if entry_date else 0
                cash += proceeds
                trades.append({
                    "date": date_str, "action": "SELL", "price": round(price, 2),
                    "shares": shares, "value": round(proceeds, 2),
                    "pnl": round(pnl, 2), "hold_days": hold_days,
                })
                shares = 0
                entry_price = 0.0

            # Record equity
            equity = cash + shares * price
            equity_curve.append({"date": date_str, "value": round(equity, 2)})

        # Final value
        final_value = cash + shares * df.iloc[-1]["close"]

        # Metrics
        total_return = (final_value - capital) / capital
        days = (df.index[-1] - df.index[0]).days or 1
        annualized_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0

        # Max drawdown
        eq_values = [e["value"] for e in equity_curve]
        peak = eq_values[0]
        max_dd = 0.0
        for v in eq_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Win rate
        sell_trades = [t for t in trades if t["action"] == "SELL"]
        wins = sum(1 for t in sell_trades if t.get("pnl", 0) > 0)
        win_rate = wins / len(sell_trades) if sell_trades else 0

        # Sharpe ratio (annualized, using daily returns)
        if len(eq_values) > 1:
            returns = pd.Series(eq_values).pct_change().dropna()
            sharpe = (returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0
        else:
            sharpe = 0

        return BacktestResult(
            ticker=ticker,
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=capital,
            final_value=round(final_value, 2),
            total_return=round(total_return, 4),
            annualized_return=round(annualized_return, 4),
            max_drawdown=round(max_dd, 4),
            win_rate=round(win_rate, 4),
            num_trades=len(sell_trades),
            sharpe_ratio=round(sharpe, 2),
            equity_curve=equity_curve,
            trades=trades,
            benchmark_curve=[],
        )
