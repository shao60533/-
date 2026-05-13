"""Unified end-of-day runner for paper-trade ticker sessions.

This module owns the single execution path for "advance every active
paper-trade ticker session up to today's EOD". Used by three callers:

  1. The automated daily-snapshot scheduler (web/app.py boot) — once per
     trading day at 16:30 America/New_York, after the portfolio snapshot
     job lands.
  2. The admin manual `/api/scheduler/run-now` endpoint — fires both
     portfolio + paper-trade in a single request so an operator gets one
     combined response shape.
  3. (indirectly) the per-ticker manual endpoint
     `/api/paper/tickers/<ticker>/eod`. That one targets every sibling
     session for the (user, ticker) pair via the same ``DailyUpdater``
     pump — see :func:`run_paper_trade_eod_for_ticker`.

The runner is intentionally idempotent: ``DailyUpdater.update_session``
resumes from ``last_eod_date + 1`` and the underlying
``upsert_daily_stat`` is `INSERT … ON CONFLICT(session_id, date) DO
UPDATE`, so a same-day re-run never emits duplicate rows.

Status snapshot
---------------
``paper_trade_status_snapshot()`` exposes a compact dict for
`/api/scheduler/status` so an operator can tell whether daily stats are
fresh without scraping individual sessions. The most recent run's
:class:`EodRunSummary` is kept in module-level state purely for
read-back via that snapshot; it's *not* persisted across process
restarts and the next scheduled tick clobbers it. Tests can reset it
via :func:`_reset_last_run_for_tests`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Callable, Optional

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.eod_runner")


@dataclass
class EodSessionResult:
    """Per-session result row returned by :class:`EodRunSummary`."""

    session_id: int
    ticker: str
    user_id: int | None
    new_rows: int
    latest_date: str | None
    error: str | None = None


@dataclass
class EodRunSummary:
    """Aggregate result for one run of :func:`run_paper_trade_eod_all`.

    ``latest_date`` is the maximum daily-stat date written in this run
    across all sessions (``None`` if no rows were emitted).
    """

    ran_at: str
    total_sessions: int
    updated_sessions: int
    new_rows: int
    latest_date: str | None
    errors: list[dict] = field(default_factory=list)
    per_session: list[dict] = field(default_factory=list)
    user_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Last-run state (in-memory only) ──────────────────────────────────────────
# Mutated by every run_paper_trade_eod_all() call so /api/scheduler/status
# can surface a compact summary. NOT persisted — restart clears it; we
# also keep ``paper_trade_status_snapshot`` reading live counters from
# the store as the authoritative answer.
_LAST_RUN: EodRunSummary | None = None


def _reset_last_run_for_tests() -> None:
    """Test hook — drop the cached last-run summary."""
    global _LAST_RUN
    _LAST_RUN = None


def get_last_run() -> EodRunSummary | None:
    return _LAST_RUN


# ── Public runners ───────────────────────────────────────────────────────────


# Factory type: takes (config, store) and returns a DailyUpdater-shaped
# object exposing ``update_session(session_id) -> list[dict]``. Default
# binds the real DailyUpdater; tests inject stubs to skip yfinance.
DailyUpdaterFactory = Callable[[dict, Any], Any]


def _default_updater_factory(config: dict, store: Any) -> Any:
    # Lazy import via the package re-export rather than the submodule
    # so existing tests that monkeypatch
    # ``stock_trading_system.strategy.paper_trader.DailyUpdater`` keep
    # working — the runner now honours the same patch point the
    # per-ticker endpoint test relies on.
    from stock_trading_system.strategy.paper_trader import DailyUpdater
    return DailyUpdater(config, store)


def _list_running_ticker_sessions(store: Any, user_id: int | None) -> list[dict]:
    """All ticker-scoped sessions in ``status='running'``.

    Skips simulator replay sessions (``replay_mode`` set) — they're
    fixed-history runs that don't need fresh daily stats. Optionally
    scoped to a single user.
    """
    with store._conn() as conn:  # noqa: SLF001
        sql = (
            "SELECT id, ticker, user_id, last_eod_date, status, replay_mode "
            "FROM paper_trade_sessions "
            "WHERE ticker IS NOT NULL AND is_system = 0 "
            "AND status = 'running' "
            "AND (replay_mode IS NULL OR replay_mode = '')"
        )
        params: list[Any] = []
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(int(user_id))
        sql += " ORDER BY id ASC"
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def run_paper_trade_eod_all(
    config: dict,
    *,
    store: Any,
    user_id: int | None = None,
    target_date: str | None = None,
    updater_factory: DailyUpdaterFactory | None = None,
) -> EodRunSummary:
    """Advance every running ticker session up to ``target_date``.

    Returns a structured :class:`EodRunSummary`. Errors on individual
    sessions are captured (with the ticker + session id) and never
    aborted the whole run — one stuck ticker shouldn't strand the rest
    of the deployment's paper-trade stats.

    ``user_id=None`` (default) hits all users; passing it restricts the
    run to that user only (used by the unified manual fire-now path so
    an admin can scope a run).
    """
    global _LAST_RUN

    factory = updater_factory or _default_updater_factory
    updater = factory(config, store)

    sessions = _list_running_ticker_sessions(store, user_id)
    per_session: list[dict] = []
    errors: list[dict] = []
    total_new = 0
    updated = 0
    latest_date: str | None = None

    for sess in sessions:
        sid = int(sess["id"])
        ticker = str(sess.get("ticker") or "")
        sess_user = sess.get("user_id")
        sess_user_id = int(sess_user) if sess_user is not None else None
        row = EodSessionResult(
            session_id=sid, ticker=ticker, user_id=sess_user_id,
            new_rows=0, latest_date=None,
        )
        try:
            new_rows = updater.update_session(sid, target_date) \
                if target_date else updater.update_session(sid)
            rows = list(new_rows or [])
            row.new_rows = len(rows)
            if rows:
                # Daily updater emits rows in chronological order; the
                # last one is the most recent date written.
                last = rows[-1]
                last_date = str(last.get("date")) if isinstance(last, dict) else None
                row.latest_date = last_date
                total_new += len(rows)
                updated += 1
                if last_date and (latest_date is None or last_date > latest_date):
                    latest_date = last_date
        except Exception as e:
            row.error = f"{type(e).__name__}: {e}"
            errors.append({
                "session_id": sid, "ticker": ticker,
                "user_id": sess_user_id, "error": row.error,
            })
            logger.warning(
                "[paper_trade_eod] session_id=%s ticker=%s failed: %s",
                sid, ticker, e,
            )
        per_session.append(asdict(row))

    summary = EodRunSummary(
        ran_at=datetime.utcnow().isoformat() + "Z",
        total_sessions=len(sessions),
        updated_sessions=updated,
        new_rows=total_new,
        latest_date=latest_date,
        errors=errors,
        per_session=per_session,
        user_id=user_id,
    )
    _LAST_RUN = summary
    logger.info(
        "[paper_trade_eod] total=%d updated=%d new_rows=%d errors=%d latest=%s user=%s",
        summary.total_sessions, summary.updated_sessions, summary.new_rows,
        len(errors), latest_date, user_id,
    )
    return summary


def run_paper_trade_eod_for_ticker(
    config: dict,
    *,
    store: Any,
    ticker: str,
    user_id: int,
    target_date: str | None = None,
    updater_factory: DailyUpdaterFactory | None = None,
) -> EodRunSummary:
    """Per-ticker manual fire-now scoped to one user.

    Aggregates every (user, ticker) sibling session id via
    ``store.aggregate_ticker_session_ids`` — pre-fix the manual button
    only updated the first session, leaving legacy duplicate sessions
    stuck with stale ``last_eod_date``. Cross-user sessions are
    excluded by the ``user_id`` filter so user A's button can never
    touch user B's row.
    """
    if not ticker:
        raise ValueError("ticker required")
    if user_id is None:
        raise ValueError("user_id required (cross-user isolation)")

    factory = updater_factory or _default_updater_factory
    updater = factory(config, store)

    sibling_ids = store.aggregate_ticker_session_ids(ticker.upper(), user_id=int(user_id))
    per_session: list[dict] = []
    errors: list[dict] = []
    total_new = 0
    updated = 0
    latest_date: str | None = None
    ticker_upper = ticker.upper()

    for sid in sibling_ids:
        row = EodSessionResult(
            session_id=int(sid), ticker=ticker_upper,
            user_id=int(user_id), new_rows=0, latest_date=None,
        )
        try:
            new_rows = updater.update_session(int(sid), target_date) \
                if target_date else updater.update_session(int(sid))
            rows = list(new_rows or [])
            row.new_rows = len(rows)
            if rows:
                last = rows[-1]
                last_date = str(last.get("date")) if isinstance(last, dict) else None
                row.latest_date = last_date
                total_new += len(rows)
                updated += 1
                if last_date and (latest_date is None or last_date > latest_date):
                    latest_date = last_date
        except Exception as e:
            row.error = f"{type(e).__name__}: {e}"
            errors.append({
                "session_id": int(sid), "ticker": ticker_upper,
                "user_id": int(user_id), "error": row.error,
            })
            logger.warning(
                "[paper_trade_eod] ticker=%s session_id=%s failed: %s",
                ticker_upper, sid, e,
            )
        per_session.append(asdict(row))

    return EodRunSummary(
        ran_at=datetime.utcnow().isoformat() + "Z",
        total_sessions=len(sibling_ids),
        updated_sessions=updated,
        new_rows=total_new,
        latest_date=latest_date,
        errors=errors,
        per_session=per_session,
        user_id=int(user_id),
    )


# ── Status snapshot ──────────────────────────────────────────────────────────


def paper_trade_status_snapshot(store: Any) -> dict:
    """Compact status block surfaced by `/api/scheduler/status`.

    Live counters come straight from the store so this stays accurate
    even if the scheduler hasn't fired yet (e.g. immediately after a
    deploy). The cached ``_LAST_RUN`` is included verbatim when present
    for "what did the last automated run do" audit visibility.
    """
    today = date.today().isoformat()
    with store._conn() as conn:  # noqa: SLF001
        # Total ticker sessions (forward + replay, excludes is_system).
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM paper_trade_sessions "
            "WHERE ticker IS NOT NULL AND is_system = 0"
        ).fetchone()
        total = int(total_row["n"] if total_row else 0)

        # Newest daily-stat date across all sessions — proxy for "is the
        # paper-trade data fresh?".
        latest_row = conn.execute(
            "SELECT MAX(date) AS d FROM paper_trade_daily_stats"
        ).fetchone()
        latest = latest_row["d"] if latest_row else None

        # Stale = running session whose last_eod_date is strictly before
        # today. NULL counts as stale (never run yet).
        stale_row = conn.execute(
            "SELECT COUNT(*) AS n FROM paper_trade_sessions "
            "WHERE ticker IS NOT NULL AND is_system = 0 "
            "AND status = 'running' "
            "AND (replay_mode IS NULL OR replay_mode = '') "
            "AND (last_eod_date IS NULL OR last_eod_date < ?)",
            (today,),
        ).fetchone()
        stale = int(stale_row["n"] if stale_row else 0)

    payload: dict = {
        "total_ticker_sessions": total,
        "stale_sessions_count": stale,
        "latest_eod_date": latest,
        "last_run": _LAST_RUN.to_dict() if _LAST_RUN is not None else None,
    }
    return payload


__all__ = [
    "EodRunSummary",
    "EodSessionResult",
    "run_paper_trade_eod_all",
    "run_paper_trade_eod_for_ticker",
    "paper_trade_status_snapshot",
    "get_last_run",
    "_reset_last_run_for_tests",
]
