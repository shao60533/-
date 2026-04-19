"""Migration: create task_events table for unified progress system.

Usage:
    python -m stock_trading_system.migrations.task_events_v1 [--dry-run] [--db-path <path>]

Idempotent, auto-backup, dry-run capable.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT    NOT NULL,
    user_id    INTEGER NOT NULL,
    seq        INTEGER NOT NULL,
    event      TEXT    NOT NULL,
    payload    TEXT    NOT NULL,
    emitted_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (task_id, seq)
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_task_events_user_seq ON task_events(user_id, id DESC);",
    "CREATE INDEX IF NOT EXISTS ix_task_events_task_seq ON task_events(task_id, seq);",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def migrate(db_path: str, dry_run: bool = False) -> dict:
    db = Path(db_path)
    if not db.exists():
        print(f"ERROR: Database not found at {db}")
        sys.exit(1)

    conn = sqlite3.connect(str(db))

    if _table_exists(conn, "task_events"):
        print("✓ task_events table already exists. Nothing to do.")
        conn.close()
        return {"status": "already_migrated"}

    plan = [_SCHEMA] + _INDEXES

    if dry_run:
        print("=== DRY RUN ===\n")
        for sql in plan:
            print(sql.strip() + ";")
        print("\nNo changes made.")
        conn.close()
        return {"status": "dry_run", "plan": plan}

    # Backup
    bak = str(db) + ".pre-progress.bak"
    shutil.copy2(str(db), bak)
    print(f"✓ Backup: {bak}")

    try:
        for sql in plan:
            conn.executescript(sql)
        conn.commit()
        print("✓ task_events table created with indexes.")
        return {"status": "success"}
    except Exception as e:
        print(f"✗ Failed: {e}")
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Create task_events table")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    migrate(db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
