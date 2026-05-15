"""Unified validation runner — L0 through L5.

Usage:
    python -m stock_trading_system.validation.run_all --level smoke|full [--db-path ...] [--report ...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime
from pathlib import Path


def _run_l0_smoke(db_path: str) -> dict:
    """L0: Can we connect to DB and read basic tables?"""
    import sqlite3
    start = time.monotonic()
    results = {"pass": [], "fail": []}
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "users" in tables:
            results["pass"].append("users table exists")
        else:
            results["fail"].append("users table missing")
        if "positions" in tables:
            results["pass"].append("positions table exists")
        if "tasks" in tables:
            results["pass"].append("tasks table exists")
        if "task_events" in tables:
            results["pass"].append("task_events table exists")
        else:
            results["fail"].append("task_events table missing")
        conn.close()
    except Exception as e:
        results["fail"].append(f"DB connection failed: {e}")
    return {
        "level": "L0_smoke",
        "pass": len(results["pass"]),
        "fail": len(results["fail"]),
        "duration_sec": round(time.monotonic() - start, 1),
        "details": results,
    }


def _run_l4_data(db_path: str) -> dict:
    """L4: Business invariants."""
    from stock_trading_system.validation.invariants import run_invariants
    start = time.monotonic()
    inv = run_invariants(db_path)
    return {
        "level": "L4_data",
        "pass": len(inv["pass"]),
        "fail": len(inv["fail"]),
        "duration_sec": round(time.monotonic() - start, 1),
        "details": inv,
    }


def _run_pytest_suite(level_name: str, test_path: str) -> dict:
    """Run a pytest suite and return pass/fail counts."""
    import subprocess
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=600,
        )
        output = result.stdout + result.stderr
        # Parse pytest output for pass/fail counts
        pass_count = fail_count = 0
        for line in output.splitlines():
            if "passed" in line:
                import re
                m = re.search(r"(\d+) passed", line)
                if m:
                    pass_count = int(m.group(1))
                m2 = re.search(r"(\d+) failed", line)
                if m2:
                    fail_count = int(m2.group(1))
        return {
            "level": level_name,
            "pass": pass_count,
            "fail": fail_count,
            "duration_sec": round(time.monotonic() - start, 1),
            "details": {"output_tail": output[-500:] if output else ""},
        }
    except Exception as e:
        return {
            "level": level_name,
            "pass": 0, "fail": 1,
            "duration_sec": round(time.monotonic() - start, 1),
            "details": {"error": str(e)},
        }


def run_all(level: str, db_path: str, report_path: str | None = None) -> dict:
    from stock_trading_system.utils.timez import now_utc
    started = now_utc().isoformat()
    levels = {}

    # L0 always
    levels["L0_smoke"] = _run_l0_smoke(db_path)

    if level == "full":
        levels["L4_data"] = _run_l4_data(db_path)
        levels["L1_basic"] = _run_pytest_suite("L1_basic", "tests/validation/test_l1_basic.py")
        levels["L3_integration"] = _run_pytest_suite("L3_integration", "tests/validation/test_l3_scenarios.py")
        levels["L5_adversarial"] = _run_pytest_suite("L5_adversarial", "tests/validation/test_l5_security.py")
        levels["L2_functional"] = _run_pytest_suite("L2_functional", "tests/validation/")

    # Determine go/no-go
    total_fail = sum(lv.get("fail", 0) for lv in levels.values())
    go = "GO" if total_fail == 0 else "NO_GO"

    failures = []
    for lv_name, lv_data in levels.items():
        for f in lv_data.get("details", {}).get("fail", []):
            failures.append({"level": lv_name, "detail": f if isinstance(f, str) else f.get("name", str(f))})

    report = {
        "started_at": started,
        "finished_at": now_utc().isoformat(),
        "db_path": db_path,
        "levels": levels,
        "failures": failures,
        "go_no_go": go,
    }

    if report_path:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, default=str))
        print(f"\n✓ Report written to {p}")

    print(f"\n{'='*60}")
    print(f"OVERALL: {go}")
    for lv_name, lv_data in levels.items():
        status = lv_data.get("status", "")
        if status == "manual_required":
            print(f"  {lv_name}: ⏳ manual required")
        else:
            emoji = "✅" if lv_data["fail"] == 0 else "❌"
            print(f"  {lv_name}: {emoji} pass={lv_data['pass']} fail={lv_data['fail']} ({lv_data['duration_sec']}s)")

    return report


def main():
    parser = argparse.ArgumentParser(description="Run validation suite")
    parser.add_argument("--level", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    if args.db_path:
        db_path = args.db_path
    else:
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")

    run_all(args.level, db_path, args.report)


if __name__ == "__main__":
    main()
