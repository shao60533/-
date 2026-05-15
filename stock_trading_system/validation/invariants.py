"""Business invariant checks — 10 SQL assertions that must hold post-migration.

Usage:
    python -m stock_trading_system.validation.invariants [--db-path ...]

Any failure → exit(1) → block production deployment.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


INVARIANTS = [
    ("positions_have_owner",
     "SELECT COUNT(*) FROM positions WHERE user_id IS NULL", 0),

    ("alerts_have_owner",
     "SELECT COUNT(*) FROM alerts WHERE user_id IS NULL", 0),

    ("paper_sessions_have_owner",
     "SELECT COUNT(*) FROM paper_trade_sessions WHERE user_id IS NULL", 0),

    ("plans_have_fingerprint",
     "SELECT COUNT(*) FROM paper_trade_plans WHERE fingerprint IS NULL", 0),

    ("tasks_created_by_not_string",
     "SELECT COUNT(*) FROM tasks WHERE typeof(created_by) = 'text' AND created_by NOT GLOB '[0-9]*'", 0),

    ("analysis_have_decision",
     "SELECT COUNT(*) FROM analysis_history WHERE trade_decision IS NULL OR trade_decision = ''", 0),

    ("invites_used_by_valid",
     """SELECT COUNT(*) FROM invite_codes
        WHERE used_by IS NOT NULL
          AND used_by NOT IN (SELECT id FROM users)""", 0),

    ("task_events_user_valid",
     """SELECT COUNT(*) FROM task_events
        WHERE user_id NOT IN (SELECT id FROM users)""", 0),

    ("paper_events_session_valid",
     """SELECT COUNT(*) FROM paper_trade_strategy_events
        WHERE session_id NOT IN (SELECT id FROM paper_trade_sessions)""", 0),

    ("no_regex_literal_in_plans",
     "SELECT COUNT(*) FROM paper_trade_plans WHERE thesis = 'regex 解析'", 0),

    # hardening-iteration-v1 P0.3 / P1.5: alert_history.user_id was added
    # by p0a_data_partition but the write side (save_alert_trigger) never
    # populated it pre-fix (C5). Going forward every new row must carry
    # the owner so /api/alerts/history can filter and Telegram-bot triggers
    # are attributable.
    ("alert_history_have_owner",
     "SELECT COUNT(*) FROM alert_history WHERE user_id IS NULL", 0),

    # P1.5 also locks down: snapshots that landed via the legacy
    # post_market_close path used to land with user_id=NULL (C9). The
    # new per-user scheduler (DailySnapshotScheduler.take_snapshot_all_users)
    # always supplies a user_id; this invariant guards regressions.
    ("daily_snapshots_have_owner",
     "SELECT COUNT(*) FROM daily_snapshots WHERE user_id IS NULL", 0),

    # P1.5: every user_analysis_advice row must reference a live
    # analysis_history row — otherwise the audit trail "which analysis
    # produced this advice" is broken and the row is unreachable in UI.
    ("user_advice_links_analysis",
     """SELECT COUNT(*) FROM user_analysis_advice
        WHERE analysis_id NOT IN (SELECT id FROM analysis_history)""", 0),

    # P1.5 / P1.6: with TaskManager.submit now raising on missing
    # created_by, every new task row carries an owner. This invariant
    # catches regressions where a non-request caller forgets to pass it.
    ("tasks_have_owner",
     "SELECT COUNT(*) FROM tasks WHERE created_by IS NULL", 0),
]


def run_invariants(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    results = {"pass": [], "fail": [], "skipped": []}

    for name, sql, expected in INVARIANTS:
        try:
            actual = conn.execute(sql).fetchone()[0]
            if actual == expected:
                results["pass"].append({"name": name, "expected": expected, "actual": actual})
            else:
                results["fail"].append({"name": name, "expected": expected, "actual": actual, "sql": sql})
        except Exception as e:
            results["skipped"].append({"name": name, "error": str(e)})

    conn.close()
    results["go"] = len(results["fail"]) == 0
    results["checked_at"] = datetime.utcnow().isoformat() + "Z"
    return results


def main():
    parser = argparse.ArgumentParser(description="Run business invariant checks")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    results = run_invariants(db_path)

    print(f"\n{'='*60}")
    print(f"INVARIANTS: {'✅ ALL PASS' if results['go'] else '❌ FAILURES DETECTED'}")
    print(f"  Pass: {len(results['pass'])}")
    print(f"  Fail: {len(results['fail'])}")
    print(f"  Skipped: {len(results['skipped'])}")

    for f in results["fail"]:
        print(f"  ❌ {f['name']}: expected {f['expected']}, got {f['actual']}")
    for s in results["skipped"]:
        print(f"  ⚠ {s['name']}: {s['error']}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(results, indent=2, default=str))

    if not results["go"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
