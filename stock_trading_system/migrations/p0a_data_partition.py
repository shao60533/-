"""P0-A: Data partition migration — enforce user_id on all private tables.

Idempotent. Run with --dry-run to preview changes.

Changes:
  1. positions PK → composite (user_id, ticker)
  2. Backfill NULL user_id on positions/transactions/daily_snapshots/alerts/alert_history
  3. analysis_history: add created_by, provider, model columns
  4. Create user_analysis_advice table for personal advice split
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_utc
from pathlib import Path


def migrate(db_path: str, dry_run: bool = False) -> dict:
    path = Path(db_path)
    if not path.exists():
        return {"status": "skipped", "reason": "db not found"}

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    # Check if already migrated (positions has composite PK)
    pk_cols = [
        r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()
        if r[5] > 0  # pk flag
    ]
    if len(pk_cols) >= 2 and "user_id" in pk_cols:
        conn.close()
        return {"status": "already_migrated"}

    # Get admin user_id for backfill
    admin_row = conn.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin_row:
        conn.close()
        return {"status": "error", "reason": "No admin user found. Run multi-tenant migration first."}
    admin_id = admin_row[0]

    changes = []

    # ── 1. Backfill NULL user_id ──────────────────────────────────────
    for table in ("positions", "transactions", "daily_snapshots", "alerts"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "user_id" not in cols:
            changes.append(f"{table}: user_id column missing, skip")
            continue
        null_count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"
        ).fetchone()[0]
        if null_count > 0:
            changes.append(f"{table}: backfill {null_count} rows with user_id={admin_id}")
            if not dry_run:
                conn.execute(
                    f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
                    (admin_id,),
                )

    # alert_history: add user_id if missing, backfill via alerts.user_id
    ah_cols = [r[1] for r in conn.execute("PRAGMA table_info(alert_history)").fetchall()]
    if "user_id" not in ah_cols:
        changes.append("alert_history: add user_id column")
        if not dry_run:
            conn.execute("ALTER TABLE alert_history ADD COLUMN user_id INTEGER")
            conn.commit()
        ah_cols.append("user_id")
    # Re-check columns after potential ALTER
    ah_cols_now = [r[1] for r in conn.execute("PRAGMA table_info(alert_history)").fetchall()]
    ah_null = 0
    if "user_id" in ah_cols_now:
        ah_null = conn.execute(
            "SELECT COUNT(*) FROM alert_history WHERE user_id IS NULL"
        ).fetchone()[0]
    if ah_null > 0:
        changes.append(f"alert_history: backfill {ah_null} rows via alerts.user_id")
        if not dry_run:
            conn.execute("""
                UPDATE alert_history SET user_id = (
                    SELECT a.user_id FROM alerts a WHERE a.id = alert_history.alert_id
                ) WHERE user_id IS NULL
            """)
            # Any remaining nulls get admin
            conn.execute(
                "UPDATE alert_history SET user_id = ? WHERE user_id IS NULL",
                (admin_id,),
            )

    # ── 2. Rebuild positions with composite PK ────────────────────────
    if len(pk_cols) < 2 or "user_id" not in pk_cols:
        changes.append("positions: rebuild with composite PK (user_id, ticker)")
        if not dry_run:
            conn.executescript("""
                CREATE TABLE positions_new (
                    user_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    market TEXT NOT NULL,
                    shares REAL NOT NULL,
                    avg_cost REAL NOT NULL,
                    added_date TEXT NOT NULL,
                    PRIMARY KEY (user_id, ticker),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                INSERT OR IGNORE INTO positions_new (user_id, ticker, market, shares, avg_cost, added_date)
                    SELECT user_id, ticker, market, shares, avg_cost, added_date
                    FROM positions WHERE user_id IS NOT NULL;
                DROP TABLE positions;
                ALTER TABLE positions_new RENAME TO positions;
            """)

    # ── 3. analysis_history: add created_by, provider, model ──────────
    ana_cols = [r[1] for r in conn.execute("PRAGMA table_info(analysis_history)").fetchall()]
    for col, typ in [("created_by", "INTEGER"), ("provider", "TEXT"), ("config_hash", "TEXT")]:
        if col not in ana_cols:
            changes.append(f"analysis_history: add {col} column")
            if not dry_run:
                conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {col} {typ}")
    # model column already exists (from prior migration), skip if present
    if "model" not in ana_cols:
        if not dry_run:
            conn.execute("ALTER TABLE analysis_history ADD COLUMN model TEXT")
    # Backfill created_by (only if column now exists)
    ana_cols_now = [r[1] for r in conn.execute("PRAGMA table_info(analysis_history)").fetchall()]
    if "created_by" in ana_cols_now:
        ana_null = conn.execute(
            "SELECT COUNT(*) FROM analysis_history WHERE created_by IS NULL"
        ).fetchone()[0]
        if ana_null > 0:
            changes.append(f"analysis_history: backfill {ana_null} rows created_by={admin_id}")
            if not dry_run:
                conn.execute(
                    "UPDATE analysis_history SET created_by = ? WHERE created_by IS NULL",
                    (admin_id,),
                )
    else:
        changes.append("analysis_history: created_by column will be added (dry-run preview)")

    # ── 4. Create user_analysis_advice table ──────────────────────────
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "user_analysis_advice" not in tables:
        changes.append("user_analysis_advice: create table")
        if not dry_run:
            conn.executescript("""
                CREATE TABLE user_analysis_advice (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    analysis_id INTEGER NOT NULL,
                    holdings_context_snapshot TEXT,
                    action TEXT,
                    confidence REAL,
                    suggested_position_pct REAL,
                    entry_price_low REAL,
                    entry_price_high REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    reasoning TEXT,
                    risk_warning TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, analysis_id),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (analysis_id) REFERENCES analysis_history(id)
                );
                CREATE INDEX IF NOT EXISTS ix_uaa_user
                    ON user_analysis_advice(user_id, created_at DESC);
            """)

        # Migrate existing advice_json from analysis_history for admin
        rows = conn.execute(
            "SELECT id, advice_json FROM analysis_history WHERE advice_json IS NOT NULL AND advice_json != ''"
        ).fetchall()
        migrated = 0
        for row in rows:
            try:
                adv = json.loads(row["advice_json"]) if isinstance(row["advice_json"], str) else {}
                if not adv:
                    continue
                conn.execute("""
                    INSERT OR IGNORE INTO user_analysis_advice
                    (user_id, analysis_id, action, confidence, suggested_position_pct,
                     entry_price_low, entry_price_high, stop_loss, take_profit, reasoning)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    admin_id, row["id"],
                    adv.get("action"), _float(adv.get("confidence")),
                    _float(adv.get("suggested_position_pct")),
                    _float(adv.get("entry_price_low")), _float(adv.get("entry_price_high")),
                    _float(adv.get("stop_loss")), _float(adv.get("take_profit")),
                    adv.get("reasoning"),
                ))
                migrated += 1
            except Exception:
                continue
        if migrated:
            changes.append(f"user_analysis_advice: migrated {migrated} advice records for admin")

    if not dry_run:
        conn.commit()
    conn.close()

    return {"status": "migrated", "changes": changes}


def _float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description="P0-A data partition migration")
    parser.add_argument("db_path", nargs="?", default="data/portfolio.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Auto-backup
    if not args.dry_run:
        src = Path(args.db_path)
        if src.exists():
            # P2.5 step-2: backup filenames in UTC so they sort
            # chronologically regardless of operator timezone.
            bak = src.with_suffix(f".db.pre-p0a-{now_utc().strftime('%Y%m%d%H%M%S')}")
            shutil.copy2(src, bak)
            print(f"Backup: {bak}")

    result = migrate(args.db_path, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
