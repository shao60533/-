"""Backfill ``daily_snapshots`` from transaction history + yfinance closes.

The dashboard equity curve only shows what's in ``daily_snapshots``. When the
APScheduler job hasn't been running (or didn't exist on a given day), the
curve flat-lines on the last point we did record. This migration replays
every transaction up to each historical trading day and asks yfinance for
the closing price of each held ticker, then upserts a snapshot row.

Algorithm
---------
1. Find each user's earliest transaction. If there are none for that user
   we skip — there's nothing to value.
2. Build the list of trading days using SPY's index (yfinance's calendar
   already drops weekends + US holidays, no need to maintain our own).
3. For each ticker the user has ever held, fetch the full close-price
   series once (one ``Ticker.history`` call per ticker, not per day).
4. For each trading day:
       positions = replay all transactions WHERE timestamp <= <day> 23:59:59
       for ticker in positions.keys():
           close = price_series[ticker].asof(day) — or previous close
           with a warning if we had to walk backwards.
       total_value, total_cost, pnl = aggregate
       INSERT OR IGNORE INTO daily_snapshots(...)  — idempotent SKIP

The ``date`` column is the table's PRIMARY KEY (per the documented
single-user schema; the multi-tenant migration only added ``user_id``,
not a composite PK), so we ``INSERT OR IGNORE`` keyed on ``date`` and
treat repeats as already-done. ``--force`` switches to ``INSERT OR REPLACE``
for callers that want to recompute.

NOTE on multi-user shape: the production schema has PRIMARY KEY (date),
so two users can't both hold a snapshot for the same date — the second
user's INSERT OR IGNORE is silently dropped. The current production
deployment is single-user (one row in ``users``); per-user multi-tenant
isolation across the same dates would require a separate schema change
(composite ``UNIQUE (user_id, date)`` or PK swap), which is out of scope
here. Iteration over ``list_active()`` is still wired up so the migration
becomes correct as soon as that schema change ships.

CLI
---
    python -m stock_trading_system.migrations.backfill_daily_snapshots --dry-run
    python -m stock_trading_system.migrations.backfill_daily_snapshots --user-id=1
    python -m stock_trading_system.migrations.backfill_daily_snapshots --all-users
    python -m stock_trading_system.migrations.backfill_daily_snapshots --user-id=1 --force
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("migrations.backfill_snapshots")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_db_path(explicit: str | None) -> str:
    """Pick the DB to backfill, honoring the same overrides as the app."""
    if explicit:
        return explicit
    from stock_trading_system.config import load_config, get_config
    try:
        cfg = get_config()
    except Exception:
        cfg = load_config()
    return cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")


def _has_user_id_column(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == "user_id" for r in rows)


def _parse_timestamp(raw: str) -> datetime | None:
    """Transactions store local-time strings; tolerate a couple of formats."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


# ── Data shapes ──────────────────────────────────────────────────────────────


@dataclass
class _Stats:
    backfilled: int = 0
    skipped: int = 0
    failed: int = 0
    days_evaluated: int = 0
    fallback_prices: int = 0
    per_user: dict[int | None, dict[str, int]] = field(default_factory=dict)

    def bump(self, user_id: int | None, key: str, by: int = 1) -> None:
        bucket = self.per_user.setdefault(user_id, {})
        bucket[key] = bucket.get(key, 0) + by


# ── Core per-user backfill ───────────────────────────────────────────────────


def _load_transactions(
    conn: sqlite3.Connection,
    user_id: int | None,
    multi_tenant: bool,
) -> list[dict]:
    """Return all (sorted) transactions for a user."""
    if multi_tenant and user_id is not None:
        rows = conn.execute(
            "SELECT id, ticker, action, shares, price, timestamp "
            "FROM transactions WHERE user_id = ? ORDER BY timestamp ASC",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ticker, action, shares, price, timestamp "
            "FROM transactions ORDER BY timestamp ASC",
        ).fetchall()
    return [dict(r) for r in rows]


def _replay_positions(
    transactions: Iterable[dict],
    cutoff: datetime,
) -> dict[str, dict[str, float]]:
    """Reduce transactions up to ``cutoff`` (inclusive) into per-ticker holdings."""
    positions: dict[str, dict[str, float]] = {}
    for txn in transactions:
        ts = _parse_timestamp(txn["timestamp"])
        if ts is None or ts > cutoff:
            continue
        ticker = (txn["ticker"] or "").upper().strip()
        if not ticker:
            continue
        action = (txn["action"] or "").lower()
        shares = float(txn["shares"] or 0)
        price = float(txn["price"] or 0)
        cur = positions.setdefault(ticker, {"shares": 0.0, "cost_basis": 0.0})
        if action == "buy":
            cur["shares"] += shares
            cur["cost_basis"] += shares * price
        elif action == "sell":
            # Reduce shares + cost basis proportionally so avg_cost stays stable.
            if cur["shares"] > 0:
                avg = cur["cost_basis"] / cur["shares"]
                sold = min(shares, cur["shares"])
                cur["shares"] -= sold
                cur["cost_basis"] -= sold * avg
                if cur["shares"] <= 1e-9:
                    cur["shares"] = 0.0
                    cur["cost_basis"] = 0.0
    # Drop fully-closed positions
    return {t: p for t, p in positions.items() if p["shares"] > 0}


def _trading_days(
    start: date_cls,
    end: date_cls,
    *,
    fetch_history: Callable[[str, date_cls, date_cls], pd.DataFrame | None],
) -> list[date_cls]:
    """Use SPY's calendar (already excludes weekends + US holidays)."""
    df = fetch_history("SPY", start, end)
    if df is None or df.empty:
        # Fallback: weekday-only enumeration. Logged as a warning so the
        # operator notices when yfinance was unreachable.
        logger.warning(
            "SPY history unavailable for %s..%s; falling back to weekday enumeration",
            start, end,
        )
        out: list[date_cls] = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                out.append(cur)
            cur += timedelta(days=1)
        return out
    return [ts.date() for ts in df.index]


def _fetch_price_series(
    ticker: str,
    start: date_cls,
    end: date_cls,
    *,
    fetch_history: Callable[[str, date_cls, date_cls], pd.DataFrame | None],
    cache: dict[str, pd.Series],
) -> pd.Series | None:
    """Cache one close-price series per ticker for the whole backfill window."""
    if ticker in cache:
        return cache[ticker]
    df = fetch_history(ticker, start, end)
    if df is None or df.empty:
        cache[ticker] = pd.Series(dtype=float)
        return None
    close_col = "Close" if "Close" in df.columns else "close" if "close" in df.columns else None
    if close_col is None:
        cache[ticker] = pd.Series(dtype=float)
        return None
    series = df[close_col].copy()
    # Ensure index is plain date objects so .get() lookups by date work.
    series.index = [ts.date() if hasattr(ts, "date") else ts for ts in series.index]
    cache[ticker] = series
    return series


def _close_for(
    series: pd.Series | None,
    target: date_cls,
    *,
    earliest: date_cls,
) -> tuple[float | None, bool]:
    """Return (close, used_fallback). Walk backwards over weekends/halts."""
    if series is None or series.empty:
        return None, False
    if target in series.index:
        val = series.loc[target]
        # If duplicated index returns a Series, take the last
        if hasattr(val, "iloc"):
            val = val.iloc[-1]
        return float(val), False
    # Walk back day-by-day until we land on a known close.
    cur = target - timedelta(days=1)
    fallback_steps = 0
    while cur >= earliest and fallback_steps < 14:
        if cur in series.index:
            val = series.loc[cur]
            if hasattr(val, "iloc"):
                val = val.iloc[-1]
            return float(val), True
        cur -= timedelta(days=1)
        fallback_steps += 1
    return None, False


def _snapshot_exists(
    conn: sqlite3.Connection,
    *,
    target_date: str,
    user_id: int | None,
    multi_tenant: bool,
) -> bool:
    if multi_tenant and user_id is not None:
        row = conn.execute(
            "SELECT 1 FROM daily_snapshots WHERE date = ? AND user_id = ?",
            (target_date, user_id),
        ).fetchone()
    elif multi_tenant and user_id is None:
        # Legacy / pre-multi-tenant rows live with user_id IS NULL.
        # ``= NULL`` never matches in SQL — must use IS NULL.
        row = conn.execute(
            "SELECT 1 FROM daily_snapshots WHERE date = ? AND user_id IS NULL",
            (target_date,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM daily_snapshots WHERE date = ?",
            (target_date,),
        ).fetchone()
    return row is not None


def _upsert_snapshot(
    conn: sqlite3.Connection,
    *,
    target_date: str,
    total_value: float,
    total_cost: float,
    pnl: float,
    pnl_pct: float,
    positions_json: str,
    user_id: int | None,
    snapshots_have_user_id: bool,
    force: bool,
) -> None:
    """INSERT OR IGNORE (default) / DELETE+INSERT (--force).

    The post-multi-tenant schema declares ``UNIQUE(user_id, date)`` but
    SQLite's UNIQUE constraint treats NULL values as DISTINCT — i.e.
    multiple legacy rows with ``user_id IS NULL`` and the same date are
    all considered unique, so ``INSERT OR REPLACE`` happily appends a
    new row instead of replacing the old one. To make ``--force``
    actually overwrite, we explicitly DELETE the matching row first
    using ``IS NULL`` semantics.
    """
    if force:
        if snapshots_have_user_id:
            if user_id is None:
                conn.execute(
                    "DELETE FROM daily_snapshots "
                    "WHERE date = ? AND user_id IS NULL",
                    (target_date,),
                )
            else:
                conn.execute(
                    "DELETE FROM daily_snapshots "
                    "WHERE date = ? AND user_id = ?",
                    (target_date, user_id),
                )
        else:
            conn.execute(
                "DELETE FROM daily_snapshots WHERE date = ?",
                (target_date,),
            )

    verb = "INSERT" if force else "INSERT OR IGNORE"
    if snapshots_have_user_id:
        conn.execute(
            f"""{verb} INTO daily_snapshots
                (date, total_value, total_cost, pnl, pnl_pct, positions_json, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (target_date, total_value, total_cost, pnl, pnl_pct, positions_json, user_id),
        )
    else:
        conn.execute(
            f"""{verb} INTO daily_snapshots
                (date, total_value, total_cost, pnl, pnl_pct, positions_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (target_date, total_value, total_cost, pnl, pnl_pct, positions_json),
        )


def _default_yfinance_fetcher() -> Callable[[str, date_cls, date_cls], pd.DataFrame | None]:
    """Direct yfinance call. Isolated so tests can swap with a fake."""
    import yfinance as yf

    def fetch(ticker: str, start: date_cls, end: date_cls) -> pd.DataFrame | None:
        # yfinance treats `end` as exclusive; bump by 1 day to include it.
        df = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
        )
        if df is None or df.empty:
            return None
        return df

    return fetch


def backfill_user(
    db_path: str,
    user_id: int | None,
    *,
    dry_run: bool = False,
    force: bool = False,
    today: date_cls | None = None,
    fetch_history: Callable[[str, date_cls, date_cls], pd.DataFrame | None] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> dict:
    """Backfill snapshots for one user (or the legacy single-user DB).

    ``user_id=None`` is the pre-multi-tenant / single-user shape — we walk
    the whole transactions table and ignore the ``user_id`` filter.
    """
    today = today or date_cls.today()
    fetch_history = fetch_history or _default_yfinance_fetcher()
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        # Match TaskStore's WAL setup so this connection plays nicely with
        # concurrent task-progress writes from the same process.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        multi_tenant = _has_user_id_column(conn, "transactions")
        snapshots_have_user_id = _has_user_id_column(conn, "daily_snapshots")
        txns = _load_transactions(conn, user_id, multi_tenant)
        if not txns:
            logger.info("user=%s: no transactions, nothing to backfill", user_id)
            return {"user_id": user_id, "status": "skipped_no_txns",
                    "backfilled": 0, "skipped": 0, "failed": 0,
                    "fallback_prices": 0, "days_evaluated": 0}

        first_ts = _parse_timestamp(txns[0]["timestamp"])
        if first_ts is None:
            logger.error("user=%s: earliest transaction has unparseable timestamp %r",
                         user_id, txns[0]["timestamp"])
            return {"user_id": user_id, "status": "error_bad_timestamp",
                    "backfilled": 0, "skipped": 0, "failed": 1,
                    "fallback_prices": 0, "days_evaluated": 0}

        start_date = first_ts.date()
        days = _trading_days(start_date, today, fetch_history=fetch_history)
        if not days:
            logger.warning("user=%s: no trading days between %s and %s",
                           user_id, start_date, today)
            return {"user_id": user_id, "status": "no_trading_days",
                    "backfilled": 0, "skipped": 0, "failed": 0,
                    "fallback_prices": 0, "days_evaluated": 0}

        tickers_ever = sorted({(t["ticker"] or "").upper().strip()
                               for t in txns if (t["ticker"] or "").strip()})
        price_cache: dict[str, pd.Series] = {}
        for ticker in tickers_ever:
            _fetch_price_series(
                ticker, start_date, today,
                fetch_history=fetch_history, cache=price_cache,
            )

        backfilled = skipped = failed = fallback_count = 0
        # v1.16: a ticker that has no close anywhere in the window
        # (typical for hand-typed test tickers like TEST1/TESTX/ZZZTEST)
        # used to abort the WHOLE day's backfill. Now we only abort the
        # day if every position is unvalueable. We also surface which
        # tickers needed which kind of fallback so the operator can fix
        # the underlying ticker rather than rerunning blind.
        missing_prices: set[str] = set()      # tickers with NO close in window
        skipped_tickers: set[str] = set()     # tickers we couldn't even fall back on
        fallback_prices: dict[str, str] = {}  # ticker → reason ("prior_close" / "cost_basis_fallback")
        cur_user_label = f"user={user_id}" if user_id is not None else "user=<legacy>"

        for i, day in enumerate(days):
            target_str = day.strftime("%Y-%m-%d")
            cutoff = datetime.combine(day, datetime.max.time())

            if not force and _snapshot_exists(
                conn, target_date=target_str,
                user_id=user_id, multi_tenant=snapshots_have_user_id,
            ):
                skipped += 1
                continue

            positions = _replay_positions(txns, cutoff)
            if not positions:
                # Pre-trade day: skip rather than write a flat $0 row. With
                # the existing PK-on-date schema, writing a flat row for one
                # user would block another user's real row for the same day.
                skipped += 1
                continue

            total_value = 0.0
            total_cost = 0.0
            day_used_fallback = False
            valued_positions = 0
            positions_payload: list[dict] = []

            for ticker, pos in positions.items():
                series = price_cache.get(ticker)
                close, fallback = _close_for(series, day, earliest=start_date)
                cost_basis = pos["cost_basis"]
                avg_cost = cost_basis / pos["shares"] if pos["shares"] else 0.0
                price_source: str
                price: float | None

                if close is not None:
                    price = close
                    price_source = "prior_close" if fallback else "close"
                    if fallback:
                        day_used_fallback = True
                        fallback_count += 1
                        fallback_prices[ticker] = "prior_close"
                        logger.warning(
                            "[%s] %s: %s close missing, used most recent prior close = %.4f",
                            target_str, cur_user_label, ticker, close,
                        )
                elif avg_cost > 0:
                    # No close anywhere in the window — this is usually a
                    # hand-typed test ticker (TEST1/TESTX) that yfinance
                    # doesn't know about. Cost basis is the only price we
                    # can defend valuing the position at; the resulting
                    # row at least keeps the curve continuous.
                    price = avg_cost
                    price_source = "cost_basis_fallback"
                    missing_prices.add(ticker)
                    fallback_prices[ticker] = "cost_basis_fallback"
                    fallback_count += 1
                    day_used_fallback = True
                    logger.warning(
                        "[%s] %s: %s no close in window, falling back to "
                        "cost basis = %.4f (price_source=cost_basis_fallback)",
                        target_str, cur_user_label, ticker, avg_cost,
                    )
                else:
                    # No close, no cost basis — drop just this ticker and
                    # keep going. The day's row is still written if any
                    # other position priced.
                    missing_prices.add(ticker)
                    skipped_tickers.add(ticker)
                    logger.warning(
                        "[%s] %s: %s no close AND no cost basis; "
                        "skipping ticker (price_source=missing_skipped)",
                        target_str, cur_user_label, ticker,
                    )
                    positions_payload.append({
                        "ticker": ticker,
                        "shares": round(pos["shares"], 6),
                        "avg_cost": round(avg_cost, 6),
                        "close": None,
                        "market_value": 0.0,
                        "fallback_price": False,
                        "price_source": "missing_skipped",
                    })
                    continue

                market_value = pos["shares"] * price
                total_value += market_value
                total_cost += cost_basis
                valued_positions += 1
                positions_payload.append({
                    "ticker": ticker,
                    "shares": round(pos["shares"], 6),
                    "avg_cost": round(avg_cost, 6),
                    "close": round(price, 6),
                    "market_value": round(market_value, 6),
                    "fallback_price": price_source != "close",
                    "price_source": price_source,
                })

            # Only fail the day when EVERY held position is unvalueable.
            # That's the genuine "no equity curve datapoint to draw"
            # case; partial misses still write a row so the curve stays
            # continuous and the operator can see which tickers are
            # bad via positions_json[*].price_source.
            if valued_positions == 0:
                logger.warning(
                    "[%s] %s: no position could be valued (%d held); marking day failed",
                    target_str, cur_user_label, len(positions),
                )
                failed += 1
                continue

            pnl = total_value - total_cost
            pnl_pct = (pnl / total_cost * 100.0) if total_cost > 0 else 0.0

            _persist_or_dry_run(
                conn, dry_run=dry_run, force=force,
                snapshots_have_user_id=snapshots_have_user_id,
                target_date=target_str, user_id=user_id,
                total_value=total_value, total_cost=total_cost,
                pnl=pnl, pnl_pct=pnl_pct,
                positions_json=json.dumps(positions_payload, ensure_ascii=False),
            )
            backfilled += 1
            tag = " (fallback price)" if day_used_fallback else ""
            logger.info(
                "[%s] %s: %d/%d positions valued, total=$%.2f%s ✓",
                target_str, cur_user_label,
                valued_positions, len(positions), total_value, tag,
            )

            if progress_cb:
                pct = (i + 1) / max(len(days), 1) * 100.0
                progress_cb(min(99.0, pct), f"{target_str}")

        if not dry_run:
            conn.commit()

        if missing_prices or skipped_tickers:
            logger.warning(
                "%s: backfill finished with missing_prices=%s skipped_tickers=%s",
                cur_user_label,
                sorted(missing_prices), sorted(skipped_tickers),
            )

        return {
            "user_id": user_id,
            "status": "ok",
            "backfilled": backfilled,
            "skipped": skipped,
            "failed": failed,
            "fallback_prices": fallback_count,
            # New v1.16 fields — the dashboard / completion toast can
            # surface these instead of the operator chasing logs.
            "missing_prices": sorted(missing_prices),
            "skipped_tickers": sorted(skipped_tickers),
            "fallback_prices_by_ticker": dict(fallback_prices),
            "days_evaluated": len(days),
            "tickers": tickers_ever,
            "first_date": start_date.strftime("%Y-%m-%d"),
            "last_date": today.strftime("%Y-%m-%d"),
            "dry_run": dry_run,
        }
    finally:
        conn.close()


def _persist_or_dry_run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool,
    force: bool,
    snapshots_have_user_id: bool,
    target_date: str,
    user_id: int | None,
    total_value: float,
    total_cost: float,
    pnl: float,
    pnl_pct: float,
    positions_json: str,
) -> None:
    if dry_run:
        return
    _upsert_snapshot(
        conn,
        target_date=target_date,
        total_value=total_value,
        total_cost=total_cost,
        pnl=pnl,
        pnl_pct=pnl_pct,
        positions_json=positions_json,
        user_id=user_id if snapshots_have_user_id else None,
        snapshots_have_user_id=snapshots_have_user_id,
        force=force,
    )
    # Commit per-row so SQLite releases the write lock between days. The
    # task progress writer (TaskStore.update) also touches this database
    # concurrently when this migration runs as a worker; without per-row
    # commits the tasks UPDATE blocks behind us and eventually times out.
    conn.commit()


# ── Multi-user driver ────────────────────────────────────────────────────────


def backfill_all_users(
    db_path: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    today: date_cls | None = None,
    fetch_history: Callable[[str, date_cls, date_cls], pd.DataFrame | None] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> list[dict]:
    """Iterate every active user. Falls back to single-user mode when no
    ``users`` table exists (pre-multi-tenant DBs)."""
    conn = sqlite3.connect(db_path)
    try:
        has_users = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone() is not None
    finally:
        conn.close()

    if not has_users:
        return [backfill_user(
            db_path, None,
            dry_run=dry_run, force=force, today=today,
            fetch_history=fetch_history, progress_cb=progress_cb,
        )]

    from stock_trading_system.auth.repository import UserRepository
    repo = UserRepository(db_path)
    users = repo.list_active()
    if not users:
        return []

    results: list[dict] = []
    n = len(users)
    for idx, user in enumerate(users):
        def _u_progress(pct: float, msg: str, _idx=idx):
            if progress_cb:
                # Spread per-user progress across the global bar.
                base = (_idx / n) * 100.0
                span = 100.0 / n
                progress_cb(base + (pct / 100.0) * span, f"user={user.id} {msg}")
        results.append(backfill_user(
            db_path, user.id,
            dry_run=dry_run, force=force, today=today,
            fetch_history=fetch_history, progress_cb=_u_progress,
        ))
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_summary(results: list[dict]) -> None:
    print("\n=== Backfill summary ===")
    total_b = total_s = total_f = 0
    for r in results:
        total_b += r.get("backfilled", 0)
        total_s += r.get("skipped", 0)
        total_f += r.get("failed", 0)
        uid = r.get("user_id")
        label = f"user={uid}" if uid is not None else "user=<legacy>"
        print(
            f"  {label}: backfilled={r.get('backfilled', 0)}  "
            f"skipped={r.get('skipped', 0)}  failed={r.get('failed', 0)}  "
            f"fallback_prices={r.get('fallback_prices', 0)}  "
            f"days_evaluated={r.get('days_evaluated', 0)}  "
            f"status={r.get('status')}"
        )
    print(f"TOTAL: backfilled={total_b}  skipped={total_s}  failed={total_f}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill daily_snapshots from transactions + yfinance.",
    )
    parser.add_argument("--db-path", help="Override portfolio.db path")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--user-id", type=int,
                        help="Backfill a single user's snapshots")
    target.add_argument("--all-users", action="store_true",
                        help="Backfill every active user")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be backfilled without writing")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing snapshot rows")
    args = parser.parse_args(argv)

    db_path = _resolve_db_path(args.db_path)
    if not Path(db_path).exists():
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        return 2

    if args.all_users:
        results = backfill_all_users(
            db_path, dry_run=args.dry_run, force=args.force,
        )
    elif args.user_id is not None:
        results = [backfill_user(
            db_path, args.user_id,
            dry_run=args.dry_run, force=args.force,
        )]
    else:
        # Default: legacy single-user mode (no user_id filter).
        results = [backfill_user(
            db_path, None,
            dry_run=args.dry_run, force=args.force,
        )]

    _print_summary(results)
    if args.dry_run:
        # Distinct exit code so wrappers can detect "nothing actually changed".
        for r in results:
            if r.get("backfilled"):
                print(f"需回填 {r['backfilled']} 天 ({'user='+str(r['user_id']) if r['user_id'] is not None else 'legacy'})")
        return 0
    return 0
    # NB: we return 0 even on partial failures because the operator has the
    # detailed summary; treat fatal errors via exception bubbling instead.


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
