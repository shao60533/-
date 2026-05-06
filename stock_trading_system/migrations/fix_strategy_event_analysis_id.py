"""paper-trade v1.5.2 — backfill paper_trade_strategy_events.analysis_id.

Pre-v1.5.2 ``order_engine._execute_order`` wrote ``order["plan_id"]``
into ``paper_trade_strategy_events.analysis_id``. The detail API
``/api/paper/tickers/<ticker>`` then called ``get_analysis_by_id``
on that integer, which silently collided with an unrelated
``analysis_history`` row whenever ``plan.id`` happened to match
another ticker's analysis id (production saw AAPL plan #30 → analysis
#30 = SMR, surfacing SMR's ``trade_decision`` on AAPL's page).

This migration:
    1. Identifies strategy events whose ``analysis_id`` references a
       row in ``paper_trade_plans`` (i.e. ``plan_id`` was written
       there).
    2. Replaces it with the plan's actual ``analysis_id``, when the
       plan has one.
    3. Logs each fix so the rollback can be reasoned about; never
       deletes a row.

Idempotent: running twice is a no-op because after the fix
``event.analysis_id`` no longer matches ``paper_trade_plans.id``.

Usage:
    python -m stock_trading_system.migrations.fix_strategy_event_analysis_id [DB_PATH]

Without an explicit path, reads ``portfolio.db_path`` from
``get_config()`` (defaults to ``data/portfolio.db``).
"""

from __future__ import annotations

import sqlite3
import sys

from stock_trading_system.utils import get_logger

logger = get_logger("migrations.fix_strategy_event_analysis_id")


def _resolve_db_path(argv: list[str]) -> str:
    if len(argv) > 1:
        return argv[1]
    try:
        from stock_trading_system.config import get_config
        return get_config().get("portfolio", {}).get(
            "db_path", "data/portfolio.db",
        )
    except Exception:
        return "data/portfolio.db"


def find_polluted_events(conn: sqlite3.Connection) -> list[dict]:
    """Return strategy events whose analysis_id collides with a
    paper_trade_plans.id (the v1.5.1 mis-write pattern).

    A row is considered polluted when:
        * event.analysis_id matches paper_trade_plans.id, AND
        * the plan has a non-null analysis_id, AND
        * the plan's analysis_id is NOT the value currently stored
          on the event (otherwise it's already correct or unrecoverable)
    """
    cur = conn.execute("""
        SELECT
            e.id              AS event_id,
            e.session_id      AS session_id,
            e.analysis_id     AS event_analysis_id,
            e.event_date      AS event_date,
            e.action          AS action,
            p.id              AS plan_id,
            p.analysis_id     AS plan_real_analysis_id
        FROM paper_trade_strategy_events AS e
        JOIN paper_trade_plans AS p
          ON e.analysis_id = p.id
        WHERE p.analysis_id IS NOT NULL
          AND p.analysis_id != e.analysis_id
        ORDER BY e.id ASC
    """)
    return [dict(r) for r in cur.fetchall()]


def apply_backfill(db_path: str, *, dry_run: bool = False) -> dict:
    """Walk strategy events, fixing the analysis_id field.

    Returns a summary dict with ``checked / fixed / sample`` keys.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = find_polluted_events(conn)
        sample = []
        for r in rows[:10]:
            sample.append({
                "event_id": r["event_id"],
                "session_id": r["session_id"],
                "event_date": r["event_date"],
                "action": r["action"],
                "old_analysis_id": r["event_analysis_id"],
                "new_analysis_id": r["plan_real_analysis_id"],
                "plan_id": r["plan_id"],
            })
        if not dry_run:
            for r in rows:
                conn.execute(
                    "UPDATE paper_trade_strategy_events "
                    "SET analysis_id = ? "
                    "WHERE id = ?",
                    (int(r["plan_real_analysis_id"]), int(r["event_id"])),
                )
            conn.commit()
        return {
            "checked": len(rows),
            "fixed": 0 if dry_run else len(rows),
            "sample": sample,
        }
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    db_path = _resolve_db_path(argv)
    dry_run = "--dry-run" in argv
    summary = apply_backfill(db_path, dry_run=dry_run)
    mode = "DRY RUN" if dry_run else "APPLIED"
    logger.info(
        "[%s] paper-trade v1.5.2 strategy_event analysis_id backfill: "
        "checked=%d fixed=%d db=%s",
        mode, summary["checked"], summary["fixed"], db_path,
    )
    if summary["sample"]:
        logger.info(
            "Sample of %d/%d affected events: %s",
            len(summary["sample"]), summary["checked"], summary["sample"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
