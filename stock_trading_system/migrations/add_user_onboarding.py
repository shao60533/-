"""Migration: create user_onboarding table for onboarding v1.0.

Idempotent — safe to run multiple times. Does NOT modify the users table.

Auto-runs from create_app() right after add_oauth_accounts; also runnable as
a CLI:

    python -m stock_trading_system.migrations.add_user_onboarding \\
           [--db-path <path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from stock_trading_system.utils import get_logger

logger = get_logger("migrations.add_user_onboarding")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_onboarding (
    user_id              INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    welcome_pending      INTEGER NOT NULL DEFAULT 0,
    welcomed             INTEGER NOT NULL DEFAULT 0,
    tour_completed       INTEGER NOT NULL DEFAULT 0,
    tour_skipped_at_step INTEGER,
    checklist_dismissed  INTEGER NOT NULL DEFAULT 0,
    steps_completed      TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def add_user_onboarding(db_path: str, dry_run: bool = False) -> dict:
    """Create user_onboarding if missing. Returns a status dict.

    Returns:
        {"status": "skipped_no_db"} when the DB file does not exist yet.
        {"status": "already_migrated"} when the table is already present.
        {"status": "dry_run", "plan": [...]} when dry_run is True.
        {"status": "success"} after creating the table.
    """
    db = Path(db_path)
    if not db.exists():
        logger.info(
            "DB %s does not exist yet — skipping user_onboarding migration", db
        )
        return {"status": "skipped_no_db"}

    with sqlite3.connect(str(db)) as conn:
        if _table_exists(conn, "user_onboarding"):
            return {"status": "already_migrated"}

        plan = [_SCHEMA]
        if dry_run:
            return {"status": "dry_run", "plan": plan}

        for sql in plan:
            conn.executescript(sql)
        conn.commit()

    logger.info("user_onboarding table created at %s", db_path)
    return {"status": "success"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create user_onboarding table")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    result = add_user_onboarding(db_path, dry_run=args.dry_run)
    print(result)
    if result["status"] == "skipped_no_db":
        sys.exit(1)


if __name__ == "__main__":
    main()
