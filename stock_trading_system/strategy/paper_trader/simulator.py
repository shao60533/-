"""Paper-trade simulator — replay AI signals against historical prices.

Engine flow:
  1. Load session config + signals in date range.
  2. Pre-fetch bars for all candidate tickers + benchmark (SPY).
  3. For each business day in [start, end]:
     a. Process signals dated that day → tentative trades.
     b. Check exits on open positions (stop / target / reverse / time-stop).
     c. Mark-to-market and snapshot daily equity.
  4. On the final day, force-close remaining positions.
  5. Compute metrics + per-ticker breakdown.

See PAPER_TRADE_DESIGN.md for semantic contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from stock_trading_system.utils import get_logger
from stock_trading_system.screener.v2.data_helper import DataHelper
from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore
from stock_trading_system.strategy.paper_trader.signal_loader import SignalLoader
from stock_trading_system.strategy.paper_trader.metrics import (
    compute_session_metrics, ticker_breakdown,
)

logger = get_logger("paper_trader.sim")


@dataclass
class _Position:
    """In-memory view of an open trade."""
    trade_id: int
    ticker: str
    entry_date: str
    entry_price: float
    shares: float
    stop_loss: float | None
    take_profit: float | None


@dataclass
class _Portfolio:
    cash: float
    positions: dict[str, _Position] = field(default_factory=dict)   # ticker -> Position

    def value(self, close_fn) -> tuple[float, float, int]:
        """Return (total, positions_value, open_count)."""
        pv = 0.0
        count = 0
        for pos in self.positions.values():
            px = close_fn(pos.ticker)
            if px is None:
                px = pos.entry_price   # fallback — no data
            pv += px * pos.shares
            count += 1
        return self.cash + pv, pv, count


class PaperTradeSimulator:
    """Run a single session (replay or live-snapshot) end to end."""

    def __init__(self, config: dict, store: PaperTradeStore, signals: SignalLoader,
                 data_helper: DataHelper | None = None, local_cache=None):
        self._config = config
        self._store = store
        self._signals = signals
        self._data = data_helper or DataHelper(config, local_cache)

    # ── Public entry ───────────────────────────────────────────────────

    def run(self, session_id: int, progress_cb=None) -> dict:
        cb = progress_cb or (lambda *a, **kw: None)
        sess = self._store.get_session(session_id)
        if not sess:
            raise ValueError(f"Session {session_id} not found")

        cfg = sess.get("config") or {}
        filters = cfg.get("filters") or {}
        sizing = cfg.get("sizing") or {}
        exit_rules = cfg.get("exit_rules") or {}
        cost = cfg.get("cost") or {}
        benchmark_sym = cfg.get("benchmark") or "SPY"

        start_date = sess["start_date"]
        end_date = sess.get("end_date") or datetime.now().strftime("%Y-%m-%d")

        cb(2, "加载信号")
        sig_list = self._signals.load(
            start_date=start_date, end_date=end_date,
            tickers=filters.get("tickers"),
            signals=filters.get("signals"),
        )
        signals_by_date: dict[str, list[dict]] = {}
        for s in sig_list:
            signals_by_date.setdefault(s["date"], []).append(s)

        # Prefetch all needed tickers
        all_tickers = sorted({s["ticker"] for s in sig_list})
        cb(8, f"预取价格数据（{len(all_tickers)} 只）")
        bars_map = self._prefetch_bars(all_tickers + [benchmark_sym],
                                        start_date, end_date)

        # Business-day date sequence
        dates = _business_days(start_date, end_date)
        if not dates:
            raise ValueError(f"No trading days between {start_date} and {end_date}")

        cb(12, f"开始模拟（共 {len(dates)} 个交易日）")
        self._store.update_session(session_id, status="running")

        portfolio = _Portfolio(cash=float(sess["start_capital"]))
        # For reverse-signal exits we also need to process SELL even if not in filter
        # Separately load full signal set for exit check (regardless of filters)
        full_signals = self._signals.load(start_date=start_date, end_date=end_date,
                                          tickers=None, signals=None)
        full_by_date: dict[str, list[dict]] = {}
        for s in full_signals:
            full_by_date.setdefault(s["date"], []).append(s)

        # Benchmark baseline (initial buy-and-hold of SPY)
        bench_close_start = _price_on(bars_map.get(benchmark_sym), dates[0])
        bench_shares = (float(sess["start_capital"]) / bench_close_start) if bench_close_start else 0

        # Pending tracked records for this session → map analysis_id -> tracked_id
        pending_tracked = {}
        for tr in self._store.list_tracked_by_session(session_id, status="pending", limit=10000):
            pending_tracked[tr["analysis_id"]] = tr["id"]

        # Main loop
        for i, d in enumerate(dates):
            pct = 12 + int((i / len(dates)) * 80)
            if i % max(1, len(dates) // 20) == 0:
                cb(pct, f"模拟 {d}")

            # 1. Process entry signals
            for sig in signals_by_date.get(d, []):
                self._maybe_open(
                    session_id, portfolio, sig, d, bars_map,
                    sizing, cost, pending_tracked,
                )
            # 2. Process reverse-signal exits from full signal stream
            if exit_rules.get("follow_reverse_signal", True):
                for sig in full_by_date.get(d, []):
                    self._maybe_reverse_exit(portfolio, sig, d, bars_map)

            # 3. Check stop/target/time-stop exits
            self._check_exits(portfolio, d, bars_map, exit_rules, cost)

            # 4. Snapshot equity
            total, pos_value, open_count = portfolio.value(
                lambda t: _price_on(bars_map.get(t), d)
            )
            bench_value = None
            if bench_shares:
                bp = _price_on(bars_map.get(benchmark_sym), d)
                if bp is not None:
                    bench_value = round(bp * bench_shares, 2)
            self._store.insert_equity(
                session_id, d, round(total, 2), round(portfolio.cash, 2),
                round(pos_value, 2), bench_value, open_count,
            )

        # Force close any remaining positions at the last available price
        cb(94, "强制平仓剩余头寸")
        last_date = dates[-1]
        for ticker, pos in list(portfolio.positions.items()):
            close_px = _price_on(bars_map.get(ticker), last_date) or pos.entry_price
            self._store.close_trade(pos.trade_id, last_date, close_px, "session_end")
            portfolio.cash += close_px * pos.shares
            del portfolio.positions[ticker]

        # Metrics
        cb(97, "计算指标")
        trades = self._store.list_trades(session_id)
        equity = self._store.list_equity(session_id)
        metrics = compute_session_metrics(trades, equity, float(sess["start_capital"]))
        ticker_stats = ticker_breakdown(trades)
        full_metrics = {**metrics, "ticker_breakdown": ticker_stats}
        self._store.update_session(
            session_id, status="completed",
            metrics_json=full_metrics,
            completed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        cb(100, f"完成 · 收益 {metrics['total_return_pct']:+.2f}% · {metrics['num_trades']} 笔交易")
        return {"metrics": full_metrics, "trades": len(trades), "equity": len(equity)}

    # ── Signal processing ─────────────────────────────────────────────

    def _maybe_open(
        self, session_id: int, portfolio: _Portfolio, sig: dict, d: str,
        bars_map: dict, sizing: dict, cost: dict, pending_tracked: dict,
    ) -> None:
        """Open a position from a BUY-like signal if rules allow."""
        signal_name = (sig.get("signal") or "").upper()
        if signal_name not in ("BUY", "OVERWEIGHT", "STRONG_BUY"):
            # Update tracked status for non-buy signals
            tracked_id = pending_tracked.get(sig["analysis_id"])
            if tracked_id:
                if signal_name == "HOLD":
                    self._store.update_tracked(tracked_id, status="no_action")
                elif signal_name in ("SELL", "UNDERWEIGHT", "STRONG_SELL"):
                    # SELL is handled separately in _maybe_reverse_exit
                    pass
            return

        ticker = sig["ticker"]
        tracked_id = pending_tracked.get(sig["analysis_id"])

        # Skip if already holding
        if ticker in portfolio.positions:
            if tracked_id:
                self._store.update_tracked(tracked_id, status="skipped",
                                           skip_reason="already_holding")
            return

        advice = sig.get("advice") or {}
        price_today = _price_on(bars_map.get(ticker), d)
        if price_today is None or price_today <= 0:
            if tracked_id:
                self._store.update_tracked(tracked_id, status="skipped",
                                           skip_reason="no_price_data")
            return

        # Entry price: if advice gives a range, use it; else use today's close
        entry_low = _f(advice.get("entry_price_low"))
        entry_high = _f(advice.get("entry_price_high"))
        if entry_low and entry_high and entry_low > 0 and entry_high > 0:
            # Require today's close within range (tolerant ±5%)
            lo, hi = min(entry_low, entry_high) * 0.95, max(entry_low, entry_high) * 1.05
            if not (lo <= price_today <= hi):
                if tracked_id:
                    self._store.update_tracked(tracked_id, status="skipped",
                                               skip_reason=f"price {price_today:.2f} out of entry range {lo:.2f}-{hi:.2f}")
                return
            entry_price = price_today
        else:
            entry_price = price_today

        # Apply slippage (buy pays slightly more)
        slippage = float(cost.get("slippage_bps", 0)) / 10000.0
        entry_price_eff = entry_price * (1 + slippage)

        # Position sizing
        shares = self._compute_shares(
            portfolio, entry_price_eff, advice, sizing, sig.get("ticker"),
        )
        if shares <= 0:
            if tracked_id:
                self._store.update_tracked(tracked_id, status="skipped",
                                           skip_reason="insufficient_cash_or_zero_shares")
            return

        # Commission
        commission = entry_price_eff * shares * (float(cost.get("commission_bps", 0)) / 10000.0)
        total_cost = entry_price_eff * shares + commission
        if total_cost > portfolio.cash:
            if tracked_id:
                self._store.update_tracked(tracked_id, status="skipped",
                                           skip_reason="insufficient_cash")
            return

        portfolio.cash -= total_cost

        trade = {
            "session_id": session_id, "ticker": ticker,
            "entry_analysis_id": sig["analysis_id"],
            "entry_date": d, "entry_price": round(entry_price_eff, 4),
            "shares": shares,
            "stop_loss": _f(advice.get("stop_loss")),
            "take_profit": _f(advice.get("take_profit")),
        }
        trade_id = self._store.insert_trade(trade)

        portfolio.positions[ticker] = _Position(
            trade_id=trade_id, ticker=ticker,
            entry_date=d, entry_price=entry_price_eff,
            shares=shares,
            stop_loss=trade["stop_loss"], take_profit=trade["take_profit"],
        )

        if tracked_id:
            self._store.update_tracked(tracked_id, status="executed",
                                       executed_trade_id=trade_id)

    def _maybe_reverse_exit(
        self, portfolio: _Portfolio, sig: dict, d: str, bars_map: dict,
    ) -> None:
        signal_name = (sig.get("signal") or "").upper()
        if signal_name not in ("SELL", "UNDERWEIGHT", "STRONG_SELL"):
            return
        ticker = sig["ticker"]
        pos = portfolio.positions.get(ticker)
        if not pos:
            return
        px = _price_on(bars_map.get(ticker), d)
        if px is None:
            return
        self._store.close_trade(
            pos.trade_id, d, round(float(px), 4), "reverse_signal",
            exit_analysis_id=sig.get("analysis_id"),
        )
        portfolio.cash += float(px) * pos.shares
        del portfolio.positions[ticker]

    def _check_exits(
        self, portfolio: _Portfolio, d: str, bars_map: dict,
        exit_rules: dict, cost: dict,
    ) -> None:
        """Check stop / target / time-stop on each open position."""
        use_stop = bool(exit_rules.get("use_advice_stop", True))
        use_target = bool(exit_rules.get("use_advice_target", True))
        time_stop = int(exit_rules.get("time_stop_days", 90) or 90)
        slippage = float(cost.get("slippage_bps", 0)) / 10000.0

        for ticker, pos in list(portfolio.positions.items()):
            bar = _bar_on(bars_map.get(ticker), d)
            if bar is None:
                continue
            high = float(bar.get("High") or bar.get("high") or 0)
            low = float(bar.get("Low") or bar.get("low") or 0)
            close = float(bar.get("Close") or bar.get("close") or 0)

            exit_price = None
            exit_reason = None

            # Stop loss (intraday low breach)
            if use_stop and pos.stop_loss and low <= pos.stop_loss:
                exit_price = pos.stop_loss * (1 - slippage)
                exit_reason = "stop"
            # Take profit (intraday high breach)
            elif use_target and pos.take_profit and high >= pos.take_profit:
                exit_price = pos.take_profit * (1 - slippage)
                exit_reason = "target"
            else:
                # Time-stop
                hold = _days_between(pos.entry_date, d)
                if hold >= time_stop:
                    exit_price = close * (1 - slippage)
                    exit_reason = "time_stop"

            if exit_price is not None and exit_reason:
                commission = exit_price * pos.shares * (float(cost.get("commission_bps", 0)) / 10000.0)
                proceeds = exit_price * pos.shares - commission
                self._store.close_trade(pos.trade_id, d, round(exit_price, 4), exit_reason)
                portfolio.cash += proceeds
                del portfolio.positions[ticker]

    # ── Sizing ────────────────────────────────────────────────────────

    def _compute_shares(
        self, portfolio: _Portfolio, entry_price: float,
        advice: dict, sizing: dict, ticker: str | None = None,
    ) -> int:
        """Return integer shares based on sizing rule."""
        mode = (sizing.get("mode") or "advice").lower()
        max_pct = float(sizing.get("max_single_pct") or 20) / 100.0

        # Estimate total equity as cash + current position values (approx by entry_price)
        equity = portfolio.cash
        for p in portfolio.positions.values():
            equity += p.entry_price * p.shares   # conservative; mark-to-market is similar

        if mode == "fixed_pct":
            pct = float(sizing.get("fixed_pct") or 10) / 100.0
        else:   # advice
            advice_pct = _f(advice.get("suggested_position_pct"))
            pct = (advice_pct / 100.0) if advice_pct and advice_pct > 0 else 0.10
        pct = min(pct, max_pct)

        target_dollars = min(equity * pct, portfolio.cash * 0.98)   # reserve 2% cash buffer
        if target_dollars <= 0 or entry_price <= 0:
            return 0
        return int(target_dollars // entry_price)

    # ── Price fetch ───────────────────────────────────────────────────

    def _prefetch_bars(
        self, tickers: list[str], start_date: str, end_date: str,
    ) -> dict:
        """Fetch OHLCV for all tickers once, covering [start, end] + buffer."""
        buf_start = _shift_date(start_date, -10)
        out = {}
        for t in tickers:
            try:
                df = self._data.get_bars(t, period="2y", interval="1d")
                if df is None or df.empty:
                    logger.info("No bars for %s — will skip", t)
                    continue
                out[t] = df
            except Exception as e:
                logger.warning("Prefetch failed for %s: %s", t, e)
        return out


# ── Helpers ────────────────────────────────────────────────────────────────

def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return x if not math.isnan(x) else None
    except (ValueError, TypeError):
        return None


def _days_between(a: str, b: str) -> int:
    try:
        da = datetime.strptime(a.split()[0], "%Y-%m-%d")
        db = datetime.strptime(b.split()[0], "%Y-%m-%d")
        return max(0, (db - da).days)
    except Exception:
        return 0


def _shift_date(d: str, days: int) -> str:
    try:
        dt = datetime.strptime(d.split()[0], "%Y-%m-%d")
        return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return d


def _business_days(start: str, end: str) -> list[str]:
    """All weekdays (Mon-Fri) between start and end inclusive, YYYY-MM-DD strings."""
    try:
        sd = datetime.strptime(start.split()[0], "%Y-%m-%d").date()
        ed = datetime.strptime(end.split()[0], "%Y-%m-%d").date()
    except Exception:
        return []
    if ed < sd:
        return []
    out = []
    d = sd
    while d <= ed:
        if d.weekday() < 5:   # Mon=0 ... Fri=4
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def _price_on(df, target_date: str) -> float | None:
    """Return Close on `target_date`, or nearest prior trading day's close."""
    if df is None or df.empty:
        return None
    try:
        import pandas as pd
        ts = pd.Timestamp(target_date)
        # Normalize df index to date if tz-aware
        idx = df.index
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)
        df2 = df.copy()
        df2.index = idx
        sub = df2.loc[:ts]
        if sub.empty:
            return None
        # Pick the right column name
        col = "Close" if "Close" in df2.columns else ("close" if "close" in df2.columns else None)
        if col is None:
            return None
        return float(sub.iloc[-1][col])
    except Exception:
        return None


def _bar_on(df, target_date: str) -> dict | None:
    """Return full OHLC bar as dict for target_date (or nearest prior)."""
    if df is None or df.empty:
        return None
    try:
        import pandas as pd
        ts = pd.Timestamp(target_date)
        idx = df.index
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_localize(None)
        df2 = df.copy()
        df2.index = idx
        sub = df2.loc[:ts]
        if sub.empty:
            return None
        return sub.iloc[-1].to_dict()
    except Exception:
        return None
