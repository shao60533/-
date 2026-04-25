"""One-time OAuth bootstrap for Schwab Trader API.

Reads SCHWAB_APP_KEY / SCHWAB_APP_SECRET / SCHWAB_CALLBACK_URL /
SCHWAB_TOKEN_PATH from env (source .schwab_creds first), then drives the
browser-based OAuth flow and writes the token to disk.

Run: `source .schwab_creds && python scripts/schwab_bootstrap.py`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    token_path = os.environ.get("SCHWAB_TOKEN_PATH", "data/schwab_token.json")

    if not (app_key and app_secret):
        print("ERROR: set SCHWAB_APP_KEY and SCHWAB_APP_SECRET first "
              "(source .schwab_creds)", file=sys.stderr)
        return 2

    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    from schwab import auth

    print(f"callback_url = {callback_url}")
    print(f"token_path   = {token_path}")
    print("Opening browser for Schwab OAuth consent. "
          "Log in, click Allow, wait for redirect to 127.0.0.1...\n")

    client = auth.client_from_login_flow(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=token_path,
        interactive=False,
        callback_timeout=300.0,
    )

    print(f"\nSUCCESS: token written to {token_path}")
    resp = client.get_quote("AAPL")
    print(f"smoke get_quote('AAPL'): HTTP {resp.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
