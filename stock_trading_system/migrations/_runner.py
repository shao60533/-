"""Unified migration runner.

hardening-iteration-v1 P3.4: prior to this module every migration was a
free-standing script invoked manually (``python -m stock_trading_system
.migrations.to_multi_tenant``). There was no version table, no record of
what had run, and ``fix_strategy_event_analysis_id`` / ``fix_tasks_orphan_events``
existed precisely because some prior migration had corrupted data and
nobody knew to re-run it.

Design (matches docs/design/hardening-iteration-v1.md §P3.4):

* ``applied_migrations(name, applied_at, status)`` — keyed by migration
  module name. ``status='ok'`` means it ran cleanly;  ``'baseline'``
  means we marked it as no-op for a pre-existing DB.
* Every migration module already exposes ``migrate(db_path, dry_run=False)``
  and is built to be idempotent (most check column existence / use
  ``CREATE TABLE IF NOT EXISTS``). The runner just iterates in canonical
  order and records each result.
* ``OPT_IN`` flags expensive backfills (e.g. ``backfill_daily_snapshots``
  loops yfinance per-ticker over months of history). These don't auto-
  run at boot — admins invoke them explicitly with ``--include-opt-in``.
* If a migration raises, the runner stops; later migrations may depend
  on the failed one's schema changes. The exception is logged with the
  migration name for triage.
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
from typing import Any

from stock_trading_system.utils import get_logger
from stock_trading_system.utils.timez import now_utc

logger = get_logger("migrations.runner")


# Canonical order — newer migrations append. The runner walks this list
# and skips anything already in ``applied_migrations``. NEVER reorder;
# the list IS the version history.
MIGRATIONS: list[str] = [
    "to_multi_tenant",
    "p0a_data_partition",
    "task_events_v1",
    "paper_trade_v1_3",
    "add_oauth_accounts",
    "fix_strategy_event_analysis_id",
    "fix_tasks_orphan_events",
    "backfill_daily_snapshots",
]

# Backfills that scan months of history / hit external APIs. Operators
# trigger these manually; the runner won't fire them at boot.
OPT_IN: frozenset[str] = frozenset({
    "backfill_daily_snapshots",
})

_APPLIED_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS applied_migrations (
    name        TEXT    PRIMARY KEY,
    applied_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL
);
"""


def _ensure_applied_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_APPLIED_TABLE_DDL)


def _applied_set(conn: sqlite3.Connection) -> set[str]:
    """Names whose status is 'ok' OR 'baseline' (both count as 'done')."""
    rows = conn.execute(
        "SELECT name FROM applied_migrations WHERE status IN ('ok','baseline')"
    ).fetchall()
    return {r[0] for r in rows}


def _record(conn: sqlite3.Connection, name: str, status: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO applied_migrations (name, applied_at, status) "
        "VALUES (?, ?, ?)",
        (name, now_utc().isoformat(), status),
    )
    conn.commit()


def _import_migrate(name: str):
    """Import the migration entrypoint.

    Convention: each module exposes ``migrate(db_path, dry_run=False)``.
    Two legacy modules predate the convention and expose alternate
    names; we look those up explicitly rather than guessing:

        add_oauth_accounts      → ``add_oauth_accounts(db_path, dry_run=False)``
        backfill_daily_snapshots → ``backfill_all_users(db_path)``  (OPT_IN)

    Returns a callable that accepts ``(db_path)`` and runs the migration.
    """
    mod = importlib.import_module(f"stock_trading_system.migrations.{name}")
    # Preferred new-style name.
    fn = getattr(mod, "migrate", None)
    if callable(fn):
        return fn
    # Legacy aliases — function name matches module name (or close).
    legacy_aliases = {
        "add_oauth_accounts": "add_oauth_accounts",
        "backfill_daily_snapshots": "backfill_all_users",
        "fix_strategy_event_analysis_id": "apply_backfill",
    }
    alt = legacy_aliases.get(name)
    if alt:
        fn = getattr(mod, alt, None)
        if callable(fn):
            return fn
    raise RuntimeError(
        f"migration {name!r} does not expose a callable migrate(db_path) "
        f"or a known legacy alias"
    )


def run_pending(
    db_path: str,
    *,
    include_opt_in: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run every pending migration in canonical order.

    Idempotent — already-applied entries are skipped via the
    ``applied_migrations`` table. If a migration raises, the runner
    stops and the exception is recorded in ``failed`` so downstream
    migrations that may depend on it don't run on a half-applied
    schema.

    ``dry_run=True`` reports what WOULD run but doesn't invoke any
    migrate(); useful for CI smoke checks.
    """
    summary: dict[str, Any] = {
        "ran": [],
        "skipped_done": [],
        "skipped_opt_in": [],
        "failed": [],
        "dry_run": dry_run,
    }

    conn = sqlite3.connect(db_path)
    try:
        _ensure_applied_table(conn)
        done = _applied_set(conn)
    finally:
        conn.close()

    for name in MIGRATIONS:
        if name in done:
            summary["skipped_done"].append(name)
            continue
        if name in OPT_IN and not include_opt_in:
            summary["skipped_opt_in"].append(name)
            continue
        if dry_run:
            summary["ran"].append({"name": name, "dry_run": True})
            continue
        try:
            migrate = _import_migrate(name)
            logger.info("Running migration: %s", name)
            result = migrate(db_path)
            conn = sqlite3.connect(db_path)
            try:
                _record(conn, name, status="ok")
            finally:
                conn.close()
            summary["ran"].append({"name": name, "result": result})
        except Exception as e:  # noqa: BLE001
            logger.exception("Migration failed: %s", name)
            summary["failed"].append({"name": name, "error": str(e)[:300]})
            break

    return summary


def mark_baseline(db_path: str, names: list[str]) -> int:
    """Mark a list of migration names as 'baseline' — meaning the DB
    was already at that schema before this runner existed. Returns the
    number of rows inserted/updated.

    Use case: an old Railway volume DB that has been running pre-P3.4.
    The first boot wants to record "to_multi_tenant + p0a_data_partition
    + ... have already happened, don't run them again" without actually
    re-executing the migrate() bodies (which ARE idempotent, but the
    accounting matters).
    """
    conn = sqlite3.connect(db_path)
    try:
        _ensure_applied_table(conn)
        n = 0
        for name in names:
            _record(conn, name, status="baseline")
            n += 1
        return n
    finally:
        conn.close()


def status(db_path: str) -> dict[str, Any]:
    """Snapshot of the applied_migrations table — for ops dashboards."""
    conn = sqlite3.connect(db_path)
    try:
        _ensure_applied_table(conn)
        rows = conn.execute(
            "SELECT name, applied_at, status FROM applied_migrations "
            "ORDER BY applied_at"
        ).fetchall()
    finally:
        conn.close()
    return {
        "applied": [
            {"name": r[0], "applied_at": r[1], "status": r[2]} for r in rows
        ],
        "canonical_order": list(MIGRATIONS),
        "opt_in": sorted(OPT_IN),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def _main() -> None:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Run pending migrations")
    p.add_argument("--db-path", default=None,
                   help="Override config.portfolio.db_path")
    p.add_argument("--include-opt-in", action="store_true",
                   help="Also run expensive backfill migrations")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would run without executing")
    p.add_argument("--status", action="store_true",
                   help="Print the applied_migrations table and exit")
    args = p.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    if args.status:
        print(json.dumps(status(db_path), indent=2))
        return

    result = run_pending(
        db_path,
        include_opt_in=args.include_opt_in,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _main()
