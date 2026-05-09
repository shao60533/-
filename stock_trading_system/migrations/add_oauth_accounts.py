"""Migration: create oauth_accounts table for OAuth quick sign-in (v1.0).

Idempotent — safe to run multiple times. Does NOT modify the users table:
OAuth-only users use a placeholder password_hash via secrets.token_urlsafe so
the existing UserRepository.create() contract stays untouched and the
multi-tenant invite-code gate (`_invite_mgr.validate/redeem`) is still the
only path that mints new users.

Auto-runs from create_app() right after ensure_multi_tenant_ready(); also
runnable as a CLI:

    python -m stock_trading_system.migrations.add_oauth_accounts \\
           [--db-path <path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from stock_trading_system.utils import get_logger

logger = get_logger("migrations.add_oauth_accounts")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_accounts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider          TEXT    NOT NULL,
    provider_user_id  TEXT    NOT NULL,
    email             TEXT,
    email_verified    INTEGER NOT NULL DEFAULT 0,
    raw_profile_json  TEXT,
    access_token_enc  TEXT,
    refresh_token_enc TEXT,
    expires_at        TEXT,
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at     TEXT,
    UNIQUE(provider, provider_user_id)
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_accounts(user_id);",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def add_oauth_accounts(db_path: str, dry_run: bool = False) -> dict:
    """Create oauth_accounts if missing. Returns status dict.

    Returns:
        {"status": "already_migrated"} when the table is already present.
        {"status": "success"} after creating the table + indexes.
        {"status": "dry_run", "plan": [...]} when dry_run is True.
    """
    db = Path(db_path)
    if not db.exists():
        logger.info("DB %s does not exist yet — skipping oauth_accounts migration", db)
        return {"status": "skipped_no_db"}

    with sqlite3.connect(str(db)) as conn:
        if _table_exists(conn, "oauth_accounts"):
            return {"status": "already_migrated"}

        plan = [_SCHEMA] + _INDEXES
        if dry_run:
            return {"status": "dry_run", "plan": plan}

        for sql in plan:
            conn.executescript(sql)
        conn.commit()

    logger.info("oauth_accounts table created at %s", db_path)
    return {"status": "success"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create oauth_accounts table")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    result = add_oauth_accounts(db_path, dry_run=args.dry_run)
    print(result)
    if result["status"] == "skipped_no_db":
        sys.exit(1)


if __name__ == "__main__":
    main()
