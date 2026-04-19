"""Migration: paper-trade v1.3 schema changes (F1 + F3).

Usage:
    python -m stock_trading_system.migrations.paper_trade_v1_3 [--dry-run] [--db-path <path>]

F1: Add fingerprint, reconfirmed_count, reconfirmed_at, analysis_ids to paper_trade_plans
F3: Add executive_summary to analysis_history

Idempotent, auto-backup, dry-run capable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


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
    conn.row_factory = sqlite3.Row

    plan: list[str] = []
    summary = {"columns_added": [], "fingerprints_computed": 0}

    # ── F1: paper_trade_plans columns ──
    if _table_exists(conn, "paper_trade_plans"):
        for col, default in [
            ("fingerprint", None),
            ("reconfirmed_count", "1"),
            ("reconfirmed_at", None),
            ("analysis_ids", None),
        ]:
            if not _has_column(conn, "paper_trade_plans", col):
                sql = f"ALTER TABLE paper_trade_plans ADD COLUMN {col}"
                if col == "reconfirmed_count":
                    sql += " INTEGER DEFAULT 1"
                elif col in ("fingerprint", "reconfirmed_at", "analysis_ids"):
                    sql += " TEXT"
                plan.append(sql)
                summary["columns_added"].append(f"paper_trade_plans.{col}")

        plan.append(
            "CREATE INDEX IF NOT EXISTS ix_plans_session_ticker_fp "
            "ON paper_trade_plans(session_id, fingerprint)"
        )
        plan.append(
            "UPDATE paper_trade_plans SET analysis_ids = json_array(analysis_id) "
            "WHERE analysis_ids IS NULL AND analysis_id IS NOT NULL"
        )

    # ── F3: analysis_history.executive_summary ──
    if _table_exists(conn, "analysis_history"):
        if not _has_column(conn, "analysis_history", "executive_summary"):
            plan.append("ALTER TABLE analysis_history ADD COLUMN executive_summary TEXT")
            summary["columns_added"].append("analysis_history.executive_summary")

    if dry_run:
        print("=== DRY RUN ===\n")
        for sql in plan:
            print(sql + ";")
        print(f"\nColumns to add: {summary['columns_added']}")
        print("No changes made.")
        conn.close()
        return {"status": "dry_run", "plan": plan}

    if not summary["columns_added"]:
        print("✓ Already migrated. Nothing to do.")
        conn.close()
        return {"status": "already_migrated"}

    # ── Backup ──
    bak = str(db) + ".pre-v1_3.bak"
    shutil.copy2(str(db), bak)
    print(f"✓ Backup: {bak}")

    # ── Execute ──
    try:
        for sql in plan:
            conn.execute(sql)
        conn.commit()

        # Compute fingerprints for existing plans
        if _table_exists(conn, "paper_trade_plans") and _has_column(conn, "paper_trade_plans", "fingerprint"):
            rows = conn.execute(
                "SELECT id, plan_json FROM paper_trade_plans WHERE fingerprint IS NULL"
            ).fetchall()
            for row in rows:
                try:
                    plan_data = json.loads(row["plan_json"]) if row["plan_json"] else {}
                    fp = _compute_fingerprint(plan_data)
                    conn.execute(
                        "UPDATE paper_trade_plans SET fingerprint=? WHERE id=?",
                        (fp, row["id"]),
                    )
                    summary["fingerprints_computed"] += 1
                except Exception:
                    pass
            conn.commit()

        print(f"✓ Migration complete!")
        print(f"  Columns added: {summary['columns_added']}")
        print(f"  Fingerprints computed: {summary['fingerprints_computed']}")
        summary["status"] = "success"

    except Exception as e:
        conn.rollback()
        print(f"✗ Migration failed: {e}")
        print(f"  Restore: cp {bak} {db}")
        summary["status"] = "failed"
        raise
    finally:
        conn.close()

    return summary


def _compute_fingerprint(plan_data: dict) -> str:
    """Compute SHA1 fingerprint from plan content fields."""
    orders = plan_data.get("orders", [])
    payload = json.dumps({
        "entry_low": plan_data.get("entry_low"),
        "entry_high": plan_data.get("entry_high"),
        "stop_loss": plan_data.get("stop_loss"),
        "take_profit": plan_data.get("take_profit"),
        "rating": plan_data.get("rating"),
        "tiers": sorted(
            [(o.get("sequence", 0), str(o.get("trigger", {})), o.get("pct_target_total", 0))
             for o in orders]
        ),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Paper Trade v1.3 migration")
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
