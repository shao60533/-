"""Auto-track hook — called from analysis pipeline when a new result lands.

Writes one `analysis_tracked` row per active auto_track session.
Does NOT execute trades here; execution happens later when session.run()
is called (replay) or a daily cron sweeps live sessions (phase 3).

The hook is designed to never raise — failures are logged and swallowed.
"""

from __future__ import annotations

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.tracking")


def auto_track_analysis(
    store,
    analysis_id: int,
    ticker: str,
    signal: str,
    advice: dict | None = None,
) -> list[int]:
    """Write tracked rows for every active auto-track session. Returns list of ids."""
    if not analysis_id or not ticker:
        return []
    # Never track error-signal analyses
    if (signal or "").upper() == "ERROR":
        return []

    try:
        session_ids = store.active_auto_track_session_ids()
    except Exception as e:
        logger.warning("active_auto_track_session_ids failed: %s", e)
        return []

    if not session_ids:
        return []

    created = []
    for sid in session_ids:
        try:
            tracked_id = store.insert_tracked(
                analysis_id=analysis_id,
                ticker=ticker.upper(),
                session_id=sid,
                status="pending",
                tracked_by="auto",
            )
            created.append(tracked_id)
        except Exception as e:
            logger.warning("insert_tracked failed for session %s: %s", sid, e)
    if created:
        logger.info("Auto-tracked analysis #%s (%s %s) → sessions %s",
                    analysis_id, ticker, signal, session_ids)
    return created


def manual_track(
    store,
    analysis_id: int,
    ticker: str,
    session_id: int,
    notes: str | None = None,
) -> int | None:
    """Explicit user-triggered tracking."""
    try:
        return store.insert_tracked(
            analysis_id=analysis_id,
            ticker=ticker.upper(),
            session_id=session_id,
            status="pending",
            tracked_by="user",
            notes=notes,
        )
    except Exception as e:
        logger.warning("manual_track failed: %s", e)
        return None


def ticker_summary(store, ticker: str) -> dict:
    """Aggregate stats for a ticker's tracking history (AI hit-rate etc.)."""
    rows = store.list_tracked_by_ticker(ticker, limit=500)
    total = len(rows)
    executed = [r for r in rows if r.get("status") == "executed"]
    buy_wins = sum(1 for r in executed if (r.get("pnl_pct") or 0) > 0 and
                   (r.get("signal") or "").upper() in ("BUY", "OVERWEIGHT"))
    buy_total = sum(1 for r in executed if
                    (r.get("signal") or "").upper() in ("BUY", "OVERWEIGHT"))
    cumulative_pnl = sum((r.get("pnl") or 0) for r in executed)
    cumulative_pct = sum((r.get("pnl_pct") or 0) for r in executed)
    hold_counts = {
        "BUY": sum(1 for r in rows if (r.get("signal") or "").upper() in ("BUY", "OVERWEIGHT")),
        "SELL": sum(1 for r in rows if (r.get("signal") or "").upper() in ("SELL", "UNDERWEIGHT")),
        "HOLD": sum(1 for r in rows if (r.get("signal") or "").upper() == "HOLD"),
    }
    return {
        "ticker": ticker.upper(),
        "total_tracked": total,
        "executed": len(executed),
        "buy_win_rate_pct": round(buy_wins / buy_total * 100, 2) if buy_total else 0,
        "cumulative_pnl": round(cumulative_pnl, 2),
        "cumulative_pnl_pct": round(cumulative_pct, 2),
        "signal_counts": hold_counts,
        "timeline": rows,
    }
