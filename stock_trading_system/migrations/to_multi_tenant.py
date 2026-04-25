"""One-shot migration: single-user → multi-tenant.

Usage:
    python -m stock_trading_system.migrations.to_multi_tenant \\
           --admin-email admin@local \\
           [--admin-password <plain>]   # optional; auto-gen if absent
           [--dry-run]
           [--db-path <path>]           # override portfolio.db_path

Idempotent: if users table already has rows, exits cleanly.
Backup: copies db to <db>.pre-mt.bak before any changes.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


# ── Schema DDL ────────────────────────────────────────────────────────────────

_SCHEMA_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user'
                          CHECK(role IN ('admin','user')),
    status        TEXT    NOT NULL DEFAULT 'active'
                          CHECK(status IN ('active','deleted')),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT,
    password_reset_token      TEXT,
    password_reset_expires_at TEXT
);
"""

_SCHEMA_INVITE_CODES = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT    PRIMARY KEY,
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at  TEXT,
    used_by     INTEGER REFERENCES users(id),
    used_at     TEXT,
    revoked_at  TEXT
);
"""

_SCHEMA_USER_SETTINGS = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id),
    llm_provider   TEXT,
    notify_email   INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_SCHEMA_BOOKMARKS = """
CREATE TABLE IF NOT EXISTS analysis_bookmarks (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    analysis_id   INTEGER NOT NULL REFERENCES analysis_history(id),
    bookmarked_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note          TEXT,
    PRIMARY KEY (user_id, analysis_id)
);
"""

# Tables that need user_id column added
_PRIVATE_TABLES = [
    "positions",
    "transactions",
    "daily_snapshots",
    "alerts",
    "paper_trade_sessions",
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_positions_user ON positions(user_id, ticker);",
    "CREATE INDEX IF NOT EXISTS ix_transactions_user ON transactions(user_id, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS ix_daily_snapshots_user ON daily_snapshots(user_id, date DESC);",
    "CREATE INDEX IF NOT EXISTS ix_alerts_user ON alerts(user_id, ticker);",
    "CREATE INDEX IF NOT EXISTS ix_paper_sessions_user ON paper_trade_sessions(user_id, created_at DESC);",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_active ON users(email) WHERE status = 'active';",
]


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    return any(c[1] == column for c in cols)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _user_count(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "users"):
        return 0
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def migrate(
    db_path: str,
    admin_email: str,
    admin_password: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the migration. Returns a summary dict."""
    db = Path(db_path)
    if not db.exists():
        print(f"ERROR: Database not found at {db}")
        sys.exit(1)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # ── Idempotent check ──
    if _user_count(conn) > 0:
        print("✓ Already migrated (users table has rows). Nothing to do.")
        conn.close()
        return {"status": "already_migrated"}

    # ── Plan ──
    plan: list[str] = []
    plan.append("-- Phase 1: Create new tables")
    plan.append(_SCHEMA_USERS)
    plan.append(_SCHEMA_INVITE_CODES)
    plan.append(_SCHEMA_USER_SETTINGS)
    plan.append(_SCHEMA_BOOKMARKS)

    # Hash admin password
    admin_pwd = admin_password or secrets.token_urlsafe(12)
    import bcrypt
    pwd_hash = bcrypt.hashpw(admin_pwd.encode(), bcrypt.gensalt(rounds=12)).decode()
    admin_email_norm = admin_email.strip().lower()
    display_name = admin_email_norm.split("@")[0]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    plan.append(f"-- Phase 2: Create admin user ({admin_email_norm})")
    plan.append(
        f"INSERT INTO users (email, password_hash, display_name, role, created_at) "
        f"VALUES ('{admin_email_norm}', '<hash>', '{display_name}', 'admin', '{now}');"
    )

    plan.append("-- Phase 3: Add user_id column to private tables")
    for table in _PRIVATE_TABLES:
        if _table_exists(conn, table) and not _has_column(conn, table, "user_id"):
            plan.append(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER;")
            plan.append(f"UPDATE {table} SET user_id = <admin_id> WHERE user_id IS NULL;")

    # tasks.created_by migration
    if _table_exists(conn, "tasks") and _has_column(conn, "tasks", "created_by"):
        if not _has_column(conn, "tasks", "created_by_legacy"):
            plan.append("-- Phase 4: tasks.created_by string → FK")
            plan.append("ALTER TABLE tasks RENAME COLUMN created_by TO created_by_legacy;")
            plan.append("ALTER TABLE tasks ADD COLUMN created_by INTEGER;")
            plan.append("UPDATE tasks SET created_by = <admin_id> WHERE created_by IS NULL;")
            plan.append("CREATE INDEX IF NOT EXISTS ix_tasks_user ON tasks(created_by, created_at DESC);")

    plan.append("-- Phase 5: Indexes")
    plan.extend(_INDEXES)

    if dry_run:
        print("=== DRY RUN — planned SQL ===\n")
        for sql in plan:
            print(sql)
        print(f"\nAdmin email: {admin_email_norm}")
        print(f"Admin password: {admin_pwd}")
        print("\nNo changes made.")
        conn.close()
        return {"status": "dry_run", "plan": plan}

    # ── Backup ──
    bak = str(db) + ".pre-mt.bak"
    shutil.copy2(str(db), bak)
    print(f"✓ Backup created: {bak}")

    # ── Execute ──
    summary = {"tables_created": [], "columns_added": [], "rows_migrated": {}}

    try:
        # 1. Create new tables
        conn.executescript(_SCHEMA_USERS)
        summary["tables_created"].append("users")
        conn.executescript(_SCHEMA_INVITE_CODES)
        summary["tables_created"].append("invite_codes")
        conn.executescript(_SCHEMA_USER_SETTINGS)
        summary["tables_created"].append("user_settings")
        conn.executescript(_SCHEMA_BOOKMARKS)
        summary["tables_created"].append("analysis_bookmarks")

        # 2. Create admin
        conn.execute(
            "INSERT INTO users (email, password_hash, display_name, role, created_at) "
            "VALUES (?, ?, ?, 'admin', ?)",
            (admin_email_norm, pwd_hash, display_name, now),
        )
        conn.commit()
        admin_id = conn.execute(
            "SELECT id FROM users WHERE email = ?", (admin_email_norm,)
        ).fetchone()[0]
        print(f"✓ Admin created: {admin_email_norm} (id={admin_id})")

        # 3. Add user_id to private tables
        for table in _PRIVATE_TABLES:
            if not _table_exists(conn, table):
                continue
            if not _has_column(conn, table, "user_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")  # noqa: S608
                summary["columns_added"].append(f"{table}.user_id")
            count = conn.execute(
                f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (admin_id,)  # noqa: S608
            ).rowcount
            summary["rows_migrated"][table] = count
            conn.commit()

        # 4. tasks.created_by migration
        if _table_exists(conn, "tasks") and _has_column(conn, "tasks", "created_by"):
            if not _has_column(conn, "tasks", "created_by_legacy"):
                conn.execute("ALTER TABLE tasks RENAME COLUMN created_by TO created_by_legacy")
                conn.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER")
                summary["columns_added"].append("tasks.created_by (FK)")
            count = conn.execute(
                "UPDATE tasks SET created_by = ? WHERE created_by IS NULL", (admin_id,)
            ).rowcount
            summary["rows_migrated"]["tasks"] = count
            conn.commit()

        # 5. Indexes
        for idx_sql in _INDEXES:
            conn.execute(idx_sql)
        conn.commit()

        # 6. Validation
        for table in _PRIVATE_TABLES:
            if not _table_exists(conn, table):
                continue
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"  # noqa: S608
            ).fetchone()[0]
            assert null_count == 0, f"FAIL: {table} has {null_count} rows with NULL user_id"

        print("\n✓ Migration complete!")
        print(f"  Admin: {admin_email_norm} / {admin_pwd}")
        print(f"  Tables created: {summary['tables_created']}")
        print(f"  Columns added: {summary['columns_added']}")
        print(f"  Rows migrated: {summary['rows_migrated']}")
        summary["status"] = "success"
        summary["admin_email"] = admin_email_norm
        summary["admin_password"] = admin_pwd

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print(f"  Restore from backup: cp {bak} {db}")
        summary["status"] = "failed"
        summary["error"] = str(e)
        raise
    finally:
        conn.close()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate single-user database to multi-tenant",
    )
    parser.add_argument(
        "--admin-email", default="admin@local",
        help="Admin account email (default: admin@local)",
    )
    parser.add_argument(
        "--admin-password", default=None,
        help="Admin password (auto-generated if not provided)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned SQL without executing",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Path to portfolio.db (default: from config)",
    )
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")

    migrate(
        db_path=db_path,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
