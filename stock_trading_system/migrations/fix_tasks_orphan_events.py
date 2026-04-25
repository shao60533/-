"""Fix tasks.created_by string remnants + orphan task_events.

Usage:
    python -m stock_trading_system.migrations.fix_tasks_orphan_events [--dry-run] [--db-path ...]

Idempotent — safe to run multiple times.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys


def migrate(db_path: str, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    summary = {"tasks_fixed": 0, "events_fixed": 0, "events_deleted": 0}

    # Get admin id
    admin_row = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if not admin_row:
        print("⚠ No admin user found. Skipping.")
        conn.close()
        return {"status": "skipped"}
    admin_id = admin_row[0]

    # 1. Fix tasks.created_by string → admin id
    str_count = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE typeof(created_by)='text' AND created_by NOT GLOB '[0-9]*'"
    ).fetchone()[0]

    # 2. Fix orphan task_events
    orphan_fixable = conn.execute(
        """SELECT COUNT(*) FROM task_events
           WHERE user_id NOT IN (SELECT id FROM users)
             AND task_id IN (SELECT id FROM tasks)"""
    ).fetchone()[0]
    orphan_deletable = conn.execute(
        """SELECT COUNT(*) FROM task_events
           WHERE user_id NOT IN (SELECT id FROM users)
             AND task_id NOT IN (SELECT id FROM tasks)"""
    ).fetchone()[0]

    if dry_run:
        print(f"=== DRY RUN ===")
        print(f"  Would fix {str_count} tasks with string created_by → admin_id={admin_id}")
        print(f"  Would fix {orphan_fixable} orphan events (from tasks)")
        print(f"  Would delete {orphan_deletable} orphan events (no matching task)")
        conn.close()
        return {"status": "dry_run"}

    if str_count == 0 and orphan_fixable == 0 and orphan_deletable == 0:
        print("✓ Nothing to fix.")
        conn.close()
        return {"status": "already_clean"}

    conn.execute(
        f"UPDATE tasks SET created_by = {admin_id} WHERE typeof(created_by)='text' AND created_by NOT GLOB '[0-9]*'"
    )
    summary["tasks_fixed"] = str_count

    conn.execute(
        f"""UPDATE task_events
            SET user_id = (SELECT COALESCE(t.created_by, {admin_id}) FROM tasks t WHERE t.id = task_events.task_id)
            WHERE user_id NOT IN (SELECT id FROM users)
              AND task_id IN (SELECT id FROM tasks)"""
    )
    summary["events_fixed"] = orphan_fixable

    conn.execute(
        "DELETE FROM task_events WHERE user_id NOT IN (SELECT id FROM users)"
    )
    summary["events_deleted"] = orphan_deletable

    conn.commit()
    conn.close()
    print(f"✓ Fixed: {summary}")
    return {"status": "success", **summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    migrate(db_path, args.dry_run)


if __name__ == "__main__":
    main()
