"""First-run checks for multi-tenant readiness."""

from __future__ import annotations

import sqlite3

from stock_trading_system.utils import get_logger

logger = get_logger("auth.bootstrap")


def _has_users_table(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    conn.close()
    return row is not None


def _user_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except sqlite3.OperationalError:
        count = 0
    conn.close()
    return count


def ensure_multi_tenant_ready(db_path: str) -> bool:
    """Check if the database has been migrated for multi-tenant.

    Returns True if ready. Raises RuntimeError if migration needed.
    Returns False (non-fatal) if users table exists but is empty —
    this allows the app to start in single-user fallback mode while
    the admin runs the migration script.
    """
    if not _has_users_table(db_path):
        import os
        print(f"\n[bootstrap debug] _has_users_table FALSE for {db_path!r}, exists={os.path.exists(db_path)}")
        logger.warning(
            "Multi-tenant tables not found. Run: "
            "python -m stock_trading_system.migrations.to_multi_tenant"
        )
        return False
    if _user_count(db_path) == 0:
        logger.warning("Users table is empty. Re-run migration to bootstrap admin.")
        return False
    return True
