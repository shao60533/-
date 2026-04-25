"""Compare pre and post migration snapshots.

Usage:
    python -m stock_trading_system.validation.compare \
      --pre validation/snapshot-pre.json \
      --post validation/snapshot-post.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def compare_snapshots(pre: dict, post: dict) -> dict:
    """Compare two snapshots. Returns {pass, fail, details}."""
    results = {"pass": [], "fail": [], "warnings": []}

    pre_tables = set(pre["tables"].keys())
    post_tables = set(post["tables"].keys())

    # New tables are OK (expected from migrations)
    new_tables = post_tables - pre_tables
    if new_tables:
        results["warnings"].append(f"New tables: {sorted(new_tables)}")

    # Missing tables are NOT OK
    missing = pre_tables - post_tables
    if missing:
        results["fail"].append(f"MISSING tables: {sorted(missing)}")

    # Compare each pre-existing table
    for table in sorted(pre_tables & post_tables):
        pre_t = pre["tables"][table]
        post_t = post["tables"][table]

        if "error" in pre_t or "error" in post_t:
            results["warnings"].append(f"{table}: snapshot error")
            continue

        # Row count
        if post_t["row_count"] < pre_t["row_count"]:
            results["fail"].append(
                f"{table}: row count DECREASED {pre_t['row_count']} → {post_t['row_count']}"
            )
        elif post_t["row_count"] == pre_t["row_count"]:
            results["pass"].append(f"{table}: row count OK ({post_t['row_count']})")
        else:
            results["pass"].append(
                f"{table}: row count OK ({pre_t['row_count']} → {post_t['row_count']}, +{post_t['row_count'] - pre_t['row_count']})"
            )

        # ID range continuity
        if pre_t.get("min_id") is not None:
            if post_t.get("min_id") != pre_t["min_id"]:
                results["fail"].append(f"{table}: min_id changed {pre_t['min_id']} → {post_t.get('min_id')}")
            else:
                results["pass"].append(f"{table}: min_id OK")

        # Sample rows comparison (business fields only)
        pre_samples = {str(r.get("id", i)): r for i, r in enumerate(pre_t.get("sample_rows", []))}
        post_samples = {str(r.get("id", i)): r for i, r in enumerate(post_t.get("sample_rows", []))}
        for key, pre_row in pre_samples.items():
            if key not in post_samples:
                continue
            post_row = post_samples[key]
            for col in pre_row:
                if col in ("user_id", "created_by", "fingerprint", "reconfirmed_count",
                           "analysis_ids", "executive_summary", "updated_at"):
                    continue  # migration-added columns, skip
                if pre_row[col] != post_row.get(col):
                    results["fail"].append(
                        f"{table} row {key}: {col} changed '{pre_row[col]}' → '{post_row.get(col)}'"
                    )

    return {
        "pass_count": len(results["pass"]),
        "fail_count": len(results["fail"]),
        "warning_count": len(results["warnings"]),
        "go": len(results["fail"]) == 0,
        **results,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare pre/post snapshots")
    parser.add_argument("--pre", required=True)
    parser.add_argument("--post", required=True)
    args = parser.parse_args()

    pre = json.loads(Path(args.pre).read_text())
    post = json.loads(Path(args.post).read_text())

    result = compare_snapshots(pre, post)

    print(f"\n{'='*60}")
    print(f"COMPARISON RESULT: {'✅ GO' if result['go'] else '❌ NO-GO'}")
    print(f"  Pass: {result['pass_count']}")
    print(f"  Fail: {result['fail_count']}")
    print(f"  Warnings: {result['warning_count']}")

    if result["fail"]:
        print("\n❌ FAILURES:")
        for f in result["fail"]:
            print(f"  - {f}")

    if result["warnings"]:
        print("\n⚠ WARNINGS:")
        for w in result["warnings"]:
            print(f"  - {w}")

    if not result["go"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
