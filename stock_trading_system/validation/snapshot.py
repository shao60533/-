"""Generate a deterministic snapshot of all DB tables for pre/post migration comparison.

Usage:
    python -m stock_trading_system.validation.snapshot --out validation/snapshot-pre.json [--db-path ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _get_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _table_snapshot(conn: sqlite3.Connection, table: str, seed: int = 42) -> dict:
    """Snapshot a single table: row_count, checksum, id range, sample rows."""
    row_count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]

    # Column info
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{table}])").fetchall()]

    # Checksum: hash all rows sorted by rowid (excluding volatile fields)
    volatile = {"updated_at", "last_login_at", "emitted_at"}
    stable_cols = [c for c in cols if c not in volatile]
    rows = conn.execute(
        f"SELECT {','.join(f'[{c}]' for c in stable_cols)} FROM [{table}] ORDER BY rowid"
    ).fetchall()
    hasher = hashlib.sha1()
    for row in rows:
        hasher.update(str(row).encode())
    checksum = hasher.hexdigest()

    # ID range (if 'id' column exists)
    min_id = max_id = None
    if "id" in cols:
        r = conn.execute(f"SELECT MIN(id), MAX(id) FROM [{table}]").fetchone()
        min_id, max_id = r[0], r[1]

    # Deterministic sample (seed=42, 10 rows or 5%)
    sample_n = max(10, int(row_count * 0.05))
    sample_rows = []
    if row_count > 0:
        rng = random.Random(seed)
        indices = sorted(rng.sample(range(row_count), min(sample_n, row_count)))
        all_rows = conn.execute(
            f"SELECT * FROM [{table}] ORDER BY rowid"
        ).fetchall()
        for idx in indices:
            row_dict = {cols[i]: all_rows[idx][i] for i in range(len(cols))}
            sample_rows.append(row_dict)

    return {
        "row_count": row_count,
        "checksum": checksum,
        "columns": cols,
        "min_id": min_id,
        "max_id": max_id,
        "sample_rows": sample_rows,
    }


def generate_snapshot(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    tables = _get_tables(conn)

    from stock_trading_system.utils.timez import now_utc
    snapshot = {
        "generated_at": now_utc().isoformat(),
        "db_path": db_path,
        "tables": {},
    }

    for table in tables:
        try:
            snapshot["tables"][table] = _table_snapshot(conn, table)
        except Exception as e:
            snapshot["tables"][table] = {"error": str(e)}

    conn.close()
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Generate DB snapshot for validation")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    snapshot = generate_snapshot(db_path)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))
    print(f"✓ Snapshot written to {out}")
    print(f"  Tables: {len(snapshot['tables'])}")
    for name, info in snapshot["tables"].items():
        if isinstance(info, dict) and "row_count" in info:
            print(f"    {name}: {info['row_count']} rows")


if __name__ == "__main__":
    main()
