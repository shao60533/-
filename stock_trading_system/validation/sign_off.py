"""Generate sign-off credential for production deployment.

Usage:
    python -m stock_trading_system.validation.sign_off \
      --report validation/runs/2026-04-24/report-go.json \
      --signer admin@local \
      [--note "..."]

Requires report.go_no_go == "GO" to proceed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def sign_off(report_path: str, signer: str, note: str = "") -> dict:
    report = json.loads(Path(report_path).read_text())

    if report.get("go_no_go") != "GO":
        print(f"❌ Report says {report.get('go_no_go')} — cannot sign off.")
        print("   Fix all failures first, then re-run validation.")
        sys.exit(1)

    # Compute report hash for tamper detection
    report_hash = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode()
    ).hexdigest()

    credential = {
        "signed_at": datetime.now(timezone.utc).isoformat(),
        "signer": signer,
        "report_file": report_path,
        "report_hash_sha256": report_hash,
        "go_no_go": "GO",
        "note": note,
        "levels_summary": {
            k: {"pass": v.get("pass", 0), "fail": v.get("fail", 0)}
            for k, v in report.get("levels", {}).items()
        },
        "total_pass": sum(v.get("pass", 0) for v in report.get("levels", {}).values()),
        "total_fail": sum(v.get("fail", 0) for v in report.get("levels", {}).values()),
    }

    # Write sign-off next to report
    out_path = Path(report_path).parent / "sign-off.json"
    out_path.write_text(json.dumps(credential, indent=2, ensure_ascii=False))

    print(f"\n{'='*60}")
    print(f"✅ SIGN-OFF COMPLETE")
    print(f"   Signer:  {signer}")
    print(f"   Time:    {credential['signed_at']}")
    print(f"   Tests:   {credential['total_pass']} pass / {credential['total_fail']} fail")
    print(f"   Hash:    {report_hash[:16]}...")
    print(f"   Output:  {out_path}")
    if note:
        print(f"   Note:    {note}")
    print(f"\n   🚀 Production deployment is now authorized.")
    return credential


def main():
    parser = argparse.ArgumentParser(description="Sign off on validation report")
    parser.add_argument("--report", required=True, help="Path to report-go.json")
    parser.add_argument("--signer", required=True, help="Signer email (e.g. admin@local)")
    parser.add_argument("--note", default="", help="Optional note")
    args = parser.parse_args()

    sign_off(args.report, args.signer, args.note)


if __name__ == "__main__":
    main()
