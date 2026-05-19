"""Generate N invite codes from the CLI.

Usage:
    python scripts/gen_invites.py            # 10 codes, 30-day expiry, default admin
    python scripts/gen_invites.py -n 5 -d 7
    python scripts/gen_invites.py --no-expiry
    railway run python scripts/gen_invites.py     # against production DB

Resolves the same db_path the web app uses (config.portfolio.db_path,
default data/portfolio.db) and picks the lowest-id active admin as
created_by. Codes go to stdout one per line so you can pipe / copy.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from stock_trading_system.auth.invite import InviteCodeManager
from stock_trading_system.config import load_config


def _find_admin_id(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, email FROM users "
            "WHERE role = 'admin' AND status = 'active' "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
    if not row:
        raise SystemExit(
            "ERROR: no active admin user found in users table — "
            "create one before generating invites."
        )
    print(f"# created_by: user id={row[0]} email={row[1]}", file=sys.stderr)
    return int(row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate invite codes.")
    parser.add_argument("-n", "--count", type=int, default=10,
                        help="how many codes (default 10)")
    parser.add_argument("-d", "--days", type=int, default=30,
                        help="expires in N days (default 30)")
    parser.add_argument("--no-expiry", action="store_true",
                        help="codes never expire (overrides --days)")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be >= 1")
    if not args.no_expiry and args.days < 1:
        parser.error("--days must be >= 1 (or use --no-expiry)")

    cfg = load_config()
    db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
    print(f"# db: {db_path}", file=sys.stderr)

    admin_id = _find_admin_id(db_path)
    expires = None if args.no_expiry else args.days

    mgr = InviteCodeManager(db_path)
    codes = [mgr.generate(admin_id, expires_in_days=expires)
             for _ in range(args.count)]

    expiry_label = "no expiry" if args.no_expiry else f"{args.days}d"
    print(f"# generated {len(codes)} invite codes ({expiry_label})",
          file=sys.stderr)
    for c in codes:
        print(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
