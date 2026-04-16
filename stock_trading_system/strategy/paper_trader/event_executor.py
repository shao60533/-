"""V3: Turn a new analysis into a structured trading plan + fire immediate orders.

Flow:
  1. Ensure per-ticker session.
  2. Parse analysis into a structured multi-stage plan (plan_parser).
  3. Persist plan + planned_orders (old pending orders superseded, history preserved).
  4. Evaluate 'immediate' orders using today's bar → execute in place.
  5. Non-immediate orders stay pending for order_engine to pick up in daily_updater.

Never raises — all failures logged + swallowed.
"""

from __future__ import annotations

from datetime import datetime

from stock_trading_system.utils import get_logger
from stock_trading_system.strategy.paper_trader.ticker_session_manager import (
    ensure_ticker_session,
)
from stock_trading_system.strategy.paper_trader.plan_parser import extract_plan
from stock_trading_system.strategy.paper_trader import order_engine

logger = get_logger("paper_trader.executor")


def process_analysis(
    store,
    *,
    analysis_id: int,
    ticker: str,
    analysis_date: str,
    signal: str,
    advice: dict | None,
    current_price: float | None = None,
    today_bar: dict | None = None,
    recent_bars=None,
    qwen_provider=None,
    analysis_blob: dict | None = None,
) -> dict:
    try:
        return _inner(store, analysis_id=analysis_id, ticker=ticker,
                       analysis_date=analysis_date, signal=signal,
                       advice=advice, current_price=current_price,
                       today_bar=today_bar, recent_bars=recent_bars,
                       qwen_provider=qwen_provider,
                       analysis_blob=analysis_blob)
    except Exception as e:
        logger.warning("process_analysis failed for %s #%s: %s",
                       ticker, analysis_id, e)
        return {"ok": False, "error": str(e)}


def _inner(store, *, analysis_id, ticker, analysis_date, signal, advice,
            current_price, today_bar, recent_bars, qwen_provider, analysis_blob):
    if (signal or "").upper() == "ERROR":
        return {"ok": True, "action": "skipped", "reason": "ERROR signal"}

    sess = ensure_ticker_session(store, ticker, start_date=analysis_date)
    sid = int(sess["id"])
    start_capital = float(sess["start_capital"])

    # ── 1. Build the analysis blob that plan_parser expects ──────────
    ana_blob = dict(analysis_blob) if analysis_blob else {}
    ana_blob.setdefault("signal", signal)
    # Prefer explicit blob fields; fall back to advice text
    if isinstance(advice, dict):
        ana_blob.setdefault("advice_json", advice)
        ana_blob.setdefault("trade_decision", advice.get("reasoning") or "")
        ana_blob.setdefault("risk_assessment", advice.get("risk_warning") or "")

    plan, parse_method = extract_plan(ana_blob, advice, qwen_provider=qwen_provider)

    holding = (plan.get("holding_months_min"), plan.get("holding_months_max"))
    raw_summary = None
    if isinstance(advice, dict):
        raw_summary = advice.get("reasoning") or advice.get("executive_summary")

    plan_id = store.save_plan(
        session_id=sid, analysis_id=analysis_id,
        rating=plan.get("rating"), thesis=plan.get("thesis"),
        holding_months=holding, raw_summary=raw_summary,
        plan=plan, parse_method=parse_method,
    )

    # ── 2. Fire immediate orders using today's bar (if we have one) ──
    bar = today_bar or _bar_from_price(analysis_date, current_price)
    triggered = []
    if bar:
        triggered = order_engine.evaluate_day(
            store, sid, ticker, analysis_date, bar,
            recent_bars=recent_bars, start_capital=start_capital,
        )

    logger.info("%s analysis #%s → plan #%s (%s) %d orders, %d fired immediately",
                ticker, analysis_id, plan_id, parse_method,
                len(plan.get("orders", [])), len(triggered))

    return {
        "ok": True,
        "session_id": sid,
        "plan_id": plan_id,
        "parse_method": parse_method,
        "num_orders": len(plan.get("orders", [])),
        "triggered": triggered,
        "rating": plan.get("rating"),
        "thesis": plan.get("thesis"),
    }


def _bar_from_price(day: str, price: float | None) -> dict | None:
    if price is None or price <= 0:
        return None
    return {"date": day, "open": price, "high": price,
            "low": price, "close": price}
