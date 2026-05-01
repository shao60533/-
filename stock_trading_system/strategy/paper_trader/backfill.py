"""Chronological backfill: replay analysis_history → ticker sessions + daily stats.

Critical: events and daily snapshots must be interleaved per day so that
mark-to-market on day D reflects the position state AFTER day-D events
applied to the previous day's state.

Per-user contract (v1.16): every backfill runs in a single user's
context. We **never** pull advice off the shared ``analysis_history``
row. Per-user advice (entry/stop/take-profit/position_pct) lives in
``user_analysis_advice`` and is only readable by that user. When the
caller doesn't pass ``user_id`` (CLI / cron), or when no advice exists
for the user/analysis pair, we fall back to a conservative
shared-only plan derived from ``signal``/``trade_decision`` text.

Flow per ticker:
  1. Ensure session (scoped to user_id).
  2. Pre-fetch bars covering [earliest_analysis, today].
  3. For each business day in range:
     a. Run any analyses dated that day through the executor, using
        only the requesting user's private advice.
     b. Write one daily_stats row marked-to-market with that day's close.
     c. Stop/target checks happen inside daily_updater logic — inlined here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from stock_trading_system.utils import get_logger
from stock_trading_system.strategy.paper_trader.event_executor import process_analysis
from stock_trading_system.strategy.paper_trader.daily_updater import DailyUpdater
from stock_trading_system.strategy.paper_trader.ticker_session_manager import (
    ensure_ticker_session,
)

logger = get_logger("paper_trader.backfill")


def backfill_all(store, portfolio_db, config: dict,
                 local_cache=None, progress_cb=None,
                 user_id: int | None = None) -> dict:
    cb = progress_cb or (lambda *a, **kw: None)
    rows = portfolio_db.get_analysis_history(limit=5000)
    rows = [r for r in rows if (r.get("signal") or "").upper() != "ERROR"]
    if not rows:
        return {"ok": True, "tickers": 0, "events": 0, "days": 0}

    rows.sort(key=lambda r: (r.get("date") or "", r.get("id") or 0))
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"].upper()].append(r)

    updater = DailyUpdater(config, store, local_cache=local_cache)
    total_events = 0
    total_days = 0
    sessions = []
    cb(5, f"开始回填 {len(by_ticker)} 只股票")

    for i, (ticker, anas) in enumerate(by_ticker.items()):
        cb(int(5 + 90 * i / len(by_ticker)), f"回填 {ticker}")
        try:
            n_ev, n_d, sid = _backfill_ticker(
                store, ticker, anas, updater,
                portfolio_db=portfolio_db, user_id=user_id,
            )
            total_events += n_ev
            total_days += n_d
            if sid:
                sessions.append(sid)
        except Exception as e:
            logger.warning("Backfill %s failed: %s", ticker, e)

    cb(98, "完成")
    return {"ok": True, "tickers": len(by_ticker),
            "events": total_events, "days": total_days,
            "sessions": sessions}


def _backfill_ticker(store, ticker: str, anas: list[dict],
                     updater: DailyUpdater,
                     *, portfolio_db, user_id: int | None,
                     ) -> tuple[int, int, int | None]:
    start_date = anas[0]["date"]
    sess = ensure_ticker_session(store, ticker, start_date=start_date,
                                  user_id=user_id)
    sid = int(sess["id"])

    # Reset any prior backfill state for this ticker so re-runs are idempotent
    with store._conn() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM paper_trade_strategy_events WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM paper_trade_daily_stats WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM paper_trade_trades WHERE session_id = ?", (sid,))
        conn.execute("UPDATE paper_trade_sessions SET last_eod_date = NULL WHERE id = ?", (sid,))

    ana_by_date = defaultdict(list)
    for a in anas:
        ana_by_date[a["date"]].append(a)

    start = _parse(start_date)
    end = date.today()
    bars = updater._fetch_bars(ticker, start, end)  # noqa: SLF001

    n_events = 0
    n_days = 0
    processed_bars = {}
    if bars is not None and not bars.empty:
        idx_naive = (bars.index.tz_localize(None)
                     if bars.index.tz is not None else bars.index)
        for i, dt in enumerate(idx_naive):
            processed_bars[dt.date().isoformat()] = bars.iloc[i]

    # Walk every calendar day — events may fall on non-trading days (e.g. analysis
    # saved at 8pm Friday for a Saturday "date" field). We still book the event
    # but only emit daily_stats on trading days.
    cur = start
    while cur <= end:
        day_str = cur.isoformat()

        # 1. Apply analyses dated today
        for ana in ana_by_date.get(day_str, []):
            advice = _resolve_user_advice(portfolio_db, user_id, int(ana["id"]))
            price = None
            bar_today = processed_bars.get(day_str)
            if bar_today is not None:
                price = float(bar_today.get("close") or bar_today.get("Close") or 0) or None
            if price is None and advice:
                lo, hi = advice.get("entry_price_low"), advice.get("entry_price_high")
                if lo and hi:
                    try:
                        price = (float(lo) + float(hi)) / 2
                    except (TypeError, ValueError):
                        pass

            # Build today_bar dict for order_engine
            bar_dict = None
            if bar_today is not None:
                bar_dict = {k.lower(): bar_today.get(k) for k in
                            ("open", "Open", "high", "High",
                             "low", "Low", "close", "Close")}
                bar_dict["date"] = day_str
            # Recent history up to today for pattern triggers
            recent = None
            if bars is not None and not bars.empty:
                idx_naive = (bars.index.tz_localize(None)
                             if bars.index.tz is not None else bars.index)
                mask = idx_naive.date <= _parse(day_str)
                recent = bars.loc[mask].tail(40)
                recent = recent.rename(columns={c: c.lower() for c in recent.columns})

            # Pass shared research text only — never the legacy advice_json
            # that pre-v1.14 rows still carry. The executor falls back to
            # conservative parsing when ``advice`` is None / empty.
            ana_for_parser = {
                "signal": ana["signal"],
                "trade_decision": ana.get("trade_decision") or "",
                "risk_assessment": ana.get("risk_assessment") or "",
                "investment_debate": ana.get("investment_debate") or "",
                "market_report": ana.get("market_report") or "",
                # advice_json must reflect the *requesting user's* private
                # advice, not whatever the shared row happens to carry.
                "advice_json": advice,
            }
            res = process_analysis(store, analysis_id=int(ana["id"]),
                                   ticker=ticker, analysis_date=day_str,
                                   signal=ana["signal"],
                                   advice=advice, current_price=price,
                                   today_bar=bar_dict, recent_bars=recent,
                                   analysis_blob=ana_for_parser,
                                   user_id=user_id)
            if res.get("ok"):
                n_events += 1

        # 2. Book daily snapshot if this is a trading day
        bar = processed_bars.get(day_str)
        if bar is not None:
            stat = updater._process_day(sess, day_str, bar)  # noqa: SLF001
            if stat:
                n_days += 1
                store.update_session_last_eod(sid, day_str)

        cur += timedelta(days=1)

    return n_events, n_days, sid


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _resolve_user_advice(portfolio_db, user_id: int | None,
                          analysis_id: int) -> dict | None:
    """Return the requesting user's private advice for this analysis.

    Strict per-user lookup — never falls back to the shared row's legacy
    advice_json. ``None`` (anonymous CLI / cron path or "user has not
    rerun advice on this row") means the executor will plan from
    shared signal/trade_decision text only, which is the correct
    privacy-preserving behaviour.
    """
    if user_id is None:
        return None
    try:
        row = portfolio_db.get_user_advice(user_id, analysis_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_user_advice failed (user=%s analysis=%s): %s",
                       user_id, analysis_id, e)
        return None
    if not row:
        return None
    # Project user_analysis_advice back into the dict shape that
    # plan_parser / event_executor expect (matches advice_json schema).
    return {
        "action":                  row.get("action"),
        "confidence":              row.get("confidence"),
        "suggested_position_pct":  row.get("position_pct"),
        "entry_price_low":         row.get("entry_low"),
        "entry_price_high":        row.get("entry_high"),
        "stop_loss":               row.get("stop_loss"),
        "take_profit":             row.get("take_profit"),
        "reasoning":               row.get("reasoning") or "",
        "risk_warning":            row.get("risk_warning") or "",
    }
