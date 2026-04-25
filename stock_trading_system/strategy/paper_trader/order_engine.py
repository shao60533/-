"""Conditional-order evaluator.

Called on every trading day (by daily_updater) BEFORE the mark-to-market snapshot.
For each pending planned_order on the session, check if today's bar (plus a
short lookback for pattern triggers) satisfies the condition; if so, execute.

Execution mutates:
  - paper_trade_trades  (open / update / close)
  - paper_trade_planned_orders (pending → triggered)
  - paper_trade_strategy_events  (for the timeline)

Trigger kinds:
  immediate          → fires on the first evaluation day after creation
  price_above N      → today.high >= N (intraday touch)
  price_below N      → today.low  <= N
  breakout_retest    → within recent window: close > zone_high at least once,
                        then today.low <= zone_high and today.close >= zone_low
  trailing_ma(P)     → close < SMA(P), requires at least P prior bars
  time_stop(M)       → days since plan creation >= M * 30
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.order_engine")


def evaluate_day(store, session_id: int, ticker: str, day: str,
                 bar: dict, recent_bars: pd.DataFrame | None = None,
                 start_capital: float = 100000.0) -> list[dict]:
    """Fire any pending orders triggered by today's bar. Returns triggered list."""
    orders = store.list_orders(session_id=session_id, status="pending")
    if not orders:
        return []

    high = _get(bar, "high")
    low = _get(bar, "low")
    close = _get(bar, "close")
    if close is None:
        return []

    open_trade = store.get_open_trade(session_id, ticker)
    shares = float(open_trade["shares"]) if open_trade else 0.0

    # Compute current equity (cash + mark-to-market)
    from stock_trading_system.strategy.paper_trader.daily_updater import _derive_cash
    cash = _derive_cash(store, session_id, start_capital)
    equity = cash + shares * close

    triggered = []
    for o in orders:
        trig = o.get("trigger") or {}
        kind = trig.get("kind")
        fired, fill_price, reason = _evaluate(kind, trig, bar, recent_bars, o, store)
        if not fired:
            continue

        # Execute
        exec_res = _execute_order(store, session_id, ticker, day, o,
                                   fill_price, equity, open_trade, reason)
        if exec_res:
            triggered.append(exec_res)
            # Refresh state for subsequent orders in the same day
            open_trade = store.get_open_trade(session_id, ticker)
            shares = float(open_trade["shares"]) if open_trade else 0.0
            cash = _derive_cash(store, session_id, start_capital)
            equity = cash + shares * close

    return triggered


# ── Trigger evaluators ────────────────────────────────────────────────────

def _evaluate(kind: str, trig: dict, bar: dict, recent: pd.DataFrame | None,
              order: dict, store) -> tuple[bool, float | None, str]:
    close = _get(bar, "close")
    high = _get(bar, "high")
    low = _get(bar, "low")

    if kind == "immediate":
        return True, close, "immediate"

    if kind == "price_above":
        target = float(trig.get("price") or 0)
        if target and high is not None and high >= target:
            return True, target, f"price >= {target}"
        return False, None, ""

    if kind == "price_below":
        target = float(trig.get("price") or 0)
        if target and low is not None and low <= target:
            return True, target, f"price <= {target}"
        return False, None, ""

    if kind == "breakout_retest":
        zl = float(trig.get("zone_low") or 0)
        zh = float(trig.get("zone_high") or 0)
        if not (zl and zh and recent is not None and not recent.empty):
            return False, None, ""
        # Was there a close > zh in any of the recent bars before today?
        prior = recent.iloc[:-1] if len(recent) > 1 else recent
        broke_out = (prior.get("close", prior.get("Close")) > zh).any()
        if not broke_out:
            return False, None, ""
        # Today retests: low touches into or below zh but close stays >= zl
        if (low is not None and low <= zh) and (close is not None and close >= zl):
            return True, close, f"breakout+retest {zl}-{zh}"
        return False, None, ""

    if kind == "trailing_ma":
        period = int(trig.get("period") or 20)
        if recent is None or len(recent) < period + 1:
            return False, None, ""
        closes = recent.get("close", recent.get("Close"))
        if closes is None:
            return False, None, ""
        # Only fire when we hold a position
        open_trade = store.get_open_trade(order["session_id"],
                                            _ticker_from_session(store, order["session_id"]))
        if not open_trade:
            return False, None, ""
        ma = closes.rolling(period).mean().iloc[-1]
        if pd.isna(ma):
            return False, None, ""
        if close is not None and close < ma:
            return True, close, f"close {close:.2f} < MA{period} {ma:.2f}"
        return False, None, ""

    if kind == "time_stop":
        months = int(trig.get("months") or 0)
        if months <= 0:
            return False, None, ""
        created = order.get("created_at")
        if not created:
            return False, None, ""
        try:
            created_dt = datetime.fromisoformat(str(created).split(".")[0])
        except Exception:
            return False, None, ""
        day_dt = datetime.strptime(str(_get(bar, "date") or ""), "%Y-%m-%d") \
            if _get(bar, "date") else datetime.now()
        if (day_dt - created_dt).days >= months * 30:
            return True, close, f"time_stop {months}M reached"
        return False, None, ""

    return False, None, ""


# ── Order execution ───────────────────────────────────────────────────────

def _execute_order(store, session_id: int, ticker: str, day: str,
                    order: dict, fill_price: float | None,
                    equity: float, open_trade: dict | None,
                    reason: str) -> dict | None:
    if fill_price is None or fill_price <= 0:
        return None

    otype = order["order_type"]
    target_pct = order.get("pct_target_total") or 0.0
    target_value = equity * target_pct
    target_shares = target_value / fill_price if fill_price > 0 else 0.0

    trade_id = None
    shares_delta = 0.0
    action = "hold"

    current_shares = float(open_trade["shares"]) if open_trade else 0.0

    if otype in ("entry_initial", "entry_add"):
        if target_shares > current_shares:
            if open_trade and current_shares > 0:
                # Blend cost basis
                blended = ((float(open_trade["entry_price"]) * current_shares +
                            fill_price * (target_shares - current_shares))
                           / target_shares)
                store.update_open_trade(
                    open_trade["id"], shares=target_shares,
                    entry_price=blended,
                    stop_loss=open_trade.get("stop_loss"),
                    take_profit=open_trade.get("take_profit"),
                )
                trade_id = open_trade["id"]
                shares_delta = target_shares - current_shares
                action = "add"
            else:
                trade_id = store.insert_open_trade(
                    session_id, ticker,
                    entry_analysis_id=None, entry_date=day,
                    entry_price=fill_price, shares=target_shares,
                    stop_loss=None, take_profit=None,
                )
                shares_delta = target_shares
                action = "open"

    elif otype in ("exit_stop", "exit_target", "exit_trailing"):
        if open_trade and current_shares > 0:
            exit_reason = {"exit_stop": "stop_loss",
                           "exit_target": "take_profit",
                           "exit_trailing": "trailing_ma"}.get(otype, "exit")
            store.close_open_trade(open_trade["id"], day, fill_price, exit_reason)
            trade_id = open_trade["id"]
            shares_delta = -current_shares
            action = "close"

    if action == "hold":
        # Order fired but no effective change — still mark triggered
        store.mark_order_triggered(order["id"], triggered_date=day,
                                    triggered_price=fill_price, trade_id=None)
        return None

    # Write strategy event
    store.insert_strategy_event(
        session_id=session_id, analysis_id=order.get("plan_id") or 0,
        event_date=day,
        prev_signal=None,
        new_signal=otype.upper(),
        advice_action=otype,
        action=action,
        shares_delta=round(shares_delta, 4),
        price=fill_price,
        trade_id=trade_id,
        target_position_pct=target_pct,
        reasoning=f"{order.get('description') or ''} | {reason}",
    )
    store.mark_order_triggered(order["id"], triggered_date=day,
                                triggered_price=fill_price, trade_id=trade_id)
    logger.info("Triggered %s %s order #%s → %s Δ=%+.2f @ %.2f (%s)",
                ticker, otype, order["id"], action, shares_delta, fill_price, reason)
    return {"order_id": order["id"], "action": action,
            "price": fill_price, "shares_delta": shares_delta, "reason": reason}


# ── Helpers ───────────────────────────────────────────────────────────────

def _get(bar: Any, key: str):
    """Fetch a field from dict / pandas Series (case-insensitive)."""
    if bar is None:
        return None
    if hasattr(bar, "get"):
        v = bar.get(key) or bar.get(key.capitalize()) or bar.get(key.upper())
        return float(v) if v is not None and not (hasattr(v, "__len__") and v is None) else (v if v else None)
    try:
        return float(bar[key])
    except Exception:
        return None


def _ticker_from_session(store, session_id: int) -> str:
    s = store.get_session(session_id)
    return s["ticker"] if s else ""
