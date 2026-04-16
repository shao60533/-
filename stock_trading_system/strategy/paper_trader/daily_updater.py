"""End-of-day snapshot writer for ticker sessions.

For each running ticker session:
  1. Fetch the target trading day's OHLC via DataHelper (fallback yfinance).
  2. Check stop-loss / take-profit on the open trade — if breached, close it.
  3. Compute mark-to-market total_value, daily pnl vs prior snapshot,
     cumulative pnl vs start_capital, drawdown vs historical peak.
  4. Write one row into paper_trade_daily_stats (UPSERT).

Designed to be called daily by the scheduler or on-demand via API.
"""

from __future__ import annotations

from datetime import datetime, date, timedelta
import pandas as pd

from stock_trading_system.utils import get_logger
from stock_trading_system.screener.v2.data_helper import DataHelper

logger = get_logger("paper_trader.daily")


class DailyUpdater:
    def __init__(self, config: dict, store, data_helper: DataHelper | None = None,
                 local_cache=None):
        self._config = config
        self._store = store
        self._data = data_helper or DataHelper(config, local_cache)

    def update_session(self, session_id: int,
                       target_date: str | None = None) -> list[dict]:
        """Update one session up to target_date (inclusive). Returns new rows."""
        sess = self._store.get_session(session_id)
        if not sess or not sess.get("ticker"):
            return []
        ticker = sess["ticker"]

        last_eod = sess.get("last_eod_date") or sess["start_date"]
        start = _parse(last_eod)
        # Resume from day after last_eod (unless this is the first run)
        if sess.get("last_eod_date"):
            start = start + timedelta(days=1)
        end = _parse(target_date) if target_date else date.today()
        if start > end:
            return []

        bars = self._fetch_bars(ticker, start, end)
        if bars is None or bars.empty:
            logger.info("No bars for %s in %s..%s", ticker, start, end)
            return []

        new_rows = []
        # Normalize column case for downstream
        bars = bars.rename(columns={c: c.lower() for c in bars.columns}) \
               if any(c != c.lower() for c in bars.columns) else bars
        for i, (idx_date, row) in enumerate(bars.iterrows()):
            day_str = idx_date.strftime("%Y-%m-%d") if hasattr(idx_date, "strftime") \
                      else str(idx_date)[:10]
            # recent_bars: all bars up to and including today (for MA / breakout patterns)
            recent = bars.iloc[max(0, i - 30):i + 1]
            stat = self._process_day(sess, day_str, row, recent_bars=recent)
            if stat:
                new_rows.append(stat)
                self._store.update_session_last_eod(session_id, day_str)
        return new_rows

    # ── Internal ───────────────────────────────────────────────────────

    def _fetch_bars(self, ticker: str, start: date, end: date):
        """Pull enough history to cover [start, end]. DataHelper uses
        yfinance period strings, so pick the smallest sufficient period
        then slice to range."""
        try:
            today = date.today()
            span_days = (today - start).days
            period = "1mo" if span_days <= 25 else \
                     "3mo" if span_days <= 70 else \
                     "6mo" if span_days <= 150 else \
                     "1y" if span_days <= 340 else \
                     "2y" if span_days <= 700 else "5y"
            df = self._data.get_bars(ticker, period=period, interval="1d")
            if df is None or df.empty:
                return None
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            # Normalize to naive dates for comparison
            idx_naive = df.index.tz_localize(None) if df.index.tz is not None else df.index
            mask = (idx_naive.date >= start) & (idx_naive.date <= end)
            df = df.loc[mask]
            if df.empty:
                return None
            # Normalize column case for downstream use
            df = df.rename(columns={c: c.lower() for c in df.columns})
            return df
        except Exception as e:
            logger.warning("Fetch bars failed %s: %s", ticker, e)
            return None

    def _process_day(self, sess: dict, day: str, bar,
                     recent_bars=None) -> dict | None:
        store = self._store
        sid = int(sess["id"])
        start_capital = float(sess["start_capital"])

        # V3: evaluate pending conditional orders before MTM
        try:
            from stock_trading_system.strategy.paper_trader import order_engine
            bar_with_date = dict(bar) if hasattr(bar, "keys") else {
                k: bar[k] for k in (bar.index if hasattr(bar, "index") else [])
            }
            if hasattr(bar, "to_dict"):
                bar_with_date = bar.to_dict()
            bar_with_date["date"] = day
            order_engine.evaluate_day(
                store, sid, sess["ticker"], day, bar_with_date,
                recent_bars=recent_bars, start_capital=start_capital,
            )
        except Exception as e:
            logger.warning("order_engine failed for %s %s: %s",
                           sess["ticker"], day, e)

        open_p = float(bar.get("open") or bar.get("Open") or 0) or None
        high_p = float(bar.get("high") or bar.get("High") or 0) or None
        low_p = float(bar.get("low") or bar.get("Low") or 0) or None
        close_p = float(bar.get("close") or bar.get("Close") or 0) or None
        if not close_p:
            return None

        prev = store.last_daily_stat(sid)
        # Authoritative: shares from open_trade, cash from trades ledger.
        # prev_daily's cash can be stale when events fire between snapshots.
        open_trade = store.get_open_trade(sid, sess["ticker"])
        shares = float(open_trade["shares"]) if open_trade else 0.0
        cash = _derive_cash(store, sid, start_capital)
        prev_total = float(prev["total_value"]) if prev else start_capital

        # 1. Check stop / target intraday (high/low based)
        exit_reason = None
        exit_price = None
        if open_trade and shares > 0 and high_p and low_p:
            sl = open_trade.get("stop_loss")
            tp = open_trade.get("take_profit")
            # Stop first (conservative)
            if sl and low_p <= sl:
                exit_price = sl
                exit_reason = "stop_loss"
            elif tp and high_p >= tp:
                exit_price = tp
                exit_reason = "take_profit"

        strategy_changed = 0
        if exit_reason and open_trade:
            closed = store.close_open_trade(
                open_trade["id"], day, exit_price, exit_reason,
            )
            shares = 0.0
            strategy_changed = 1
            # Re-derive cash now that realized pnl has changed
            cash = _derive_cash(store, sid, start_capital)
            # Also record a strategy event so the timeline shows it
            store.insert_strategy_event(
                session_id=sid, analysis_id=open_trade.get("entry_analysis_id") or 0,
                event_date=day,
                prev_signal=None, new_signal=exit_reason.upper(),
                advice_action=None, action=exit_reason,
                shares_delta=-closed["shares"], price=exit_price,
                trade_id=open_trade["id"],
                reasoning=f"{exit_reason} triggered: low={low_p} high={high_p}",
            )
            logger.info("%s %s triggered %s @ %.2f", sess["ticker"], day,
                        exit_reason, exit_price)

        # 2. Max-hold time stop
        if shares > 0 and open_trade and not exit_reason:
            max_hold = int((sess.get("config") or {})
                           .get("exit_rules", {}).get("max_hold_days", 90))
            try:
                entry = datetime.strptime(open_trade["entry_date"], "%Y-%m-%d").date()
                held = (_parse(day) - entry).days
                if held >= max_hold:
                    store.close_open_trade(open_trade["id"], day, close_p,
                                           "time_stop")
                    shares = 0.0
                    strategy_changed = 1
                    cash = _derive_cash(store, sid, start_capital)
                    store.insert_strategy_event(
                        session_id=sid,
                        analysis_id=open_trade.get("entry_analysis_id") or 0,
                        event_date=day, new_signal="TIME_STOP",
                        action="time_stop",
                        shares_delta=-float(open_trade["shares"]),
                        price=close_p, trade_id=open_trade["id"],
                        reasoning=f"held {held} days ≥ {max_hold}",
                    )
            except Exception:
                pass

        # 3. Mark-to-market
        position_value = shares * close_p
        total_value = cash + position_value
        daily_pnl = total_value - prev_total
        daily_pnl_pct = (daily_pnl / prev_total * 100) if prev_total else 0
        cum_pnl = total_value - start_capital
        cum_pnl_pct = (cum_pnl / start_capital * 100) if start_capital else 0

        # Drawdown: peak of total_value from start
        peak = total_value
        if prev:
            peak = max(total_value, prev.get("total_value") or 0,
                       _get_peak(store, sid) or 0)
        dd_pct = ((total_value - peak) / peak * 100) if peak else 0

        # Active signal & days_held from latest event
        latest_evt = store.latest_strategy_event(sid)
        active_signal = latest_evt["new_signal"] if latest_evt else None
        active_aid = latest_evt["analysis_id"] if latest_evt else None

        days_held = 0
        if shares > 0 and open_trade:
            try:
                entry = datetime.strptime(open_trade["entry_date"], "%Y-%m-%d").date()
                days_held = (_parse(day) - entry).days
            except Exception:
                pass

        # Detect strategy_changed by comparing event_date to day
        if latest_evt and latest_evt.get("event_date") == day:
            strategy_changed = 1

        stat = dict(
            session_id=sid, date=day,
            open_price=open_p, high_price=high_p, low_price=low_p,
            close_price=close_p,
            position_shares=round(shares, 4),
            avg_cost=float(open_trade["entry_price"]) if open_trade and shares > 0 else None,
            position_value=round(position_value, 2),
            cash=round(cash, 2),
            total_value=round(total_value, 2),
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(daily_pnl_pct, 4),
            cum_pnl=round(cum_pnl, 2),
            cum_pnl_pct=round(cum_pnl_pct, 4),
            drawdown_pct=round(dd_pct, 4),
            active_signal=active_signal,
            active_analysis_id=active_aid,
            days_held=days_held,
            strategy_changed=strategy_changed,
        )
        store.upsert_daily_stat(**stat)
        return stat


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _derive_cash(store, session_id: int, start_capital: float) -> float:
    """cash = start_capital - open_position_cost + realized_pnl."""
    with store._conn() as conn:  # noqa: SLF001
        oc = conn.execute(
            """SELECT COALESCE(SUM(entry_price * shares), 0) AS c
               FROM paper_trade_trades
               WHERE session_id = ? AND exit_date IS NULL""",
            (session_id,)).fetchone()
        rp = conn.execute(
            """SELECT COALESCE(SUM(pnl), 0) AS r
               FROM paper_trade_trades
               WHERE session_id = ? AND exit_date IS NOT NULL""",
            (session_id,)).fetchone()
    return float(start_capital) - float(oc["c"] or 0) + float(rp["r"] or 0)


def _get_peak(store, sid: int) -> float:
    with store._conn() as conn:  # noqa: SLF001
        row = conn.execute(
            "SELECT MAX(total_value) as p FROM paper_trade_daily_stats WHERE session_id = ?",
            (sid,),
        ).fetchone()
        return float(row["p"]) if row and row["p"] is not None else 0.0
