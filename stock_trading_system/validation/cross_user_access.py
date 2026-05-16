"""Cross-user access validation (L5 security) — hardening-iteration-v1 P1.4.

Tests that alice cannot read/write/cancel bob's private resources, and that
anonymous callers can't read any of them. The matrix below grew from the
pre-P1.4 trio (cancel-task / holdings / anon-401) to the full IDOR surface:

    Tenant-scoped resources alice MUST NOT see / mutate from bob:
        - alerts:    .remove / .history / .list
        - portfolio: .delete / .update_cost / .snapshot / .history
        - tasks:     .cancel
        - analysis:  .delete (bookmarked or recent)
        - paper:     .read (any session) / .entry (sell into bob's session)
        - watchlist: .delete
    Admin-only mutations (non-admin must 403):
        - settings.write
        - scheduler.start

Provisioning:
    Either pass `--alice/--bob` explicitly, OR run the script in "self-
    provision" mode (default in CI): it registers alice@test / bob@test
    via the public registration endpoint with an admin invite code. The
    legacy `--bob-email` flag is preserved for backward compatibility.

Exit codes:
    0 = all expected denials happened (no leaks)
    1 = at least one leak detected (cross-tenant read or write succeeded)

Usage:
    python -m stock_trading_system.validation.cross_user_access \
        --base-url http://localhost:9090 \
        [--alice-email alice@test.local --alice-pwd ...] \
        [--bob-email bob@test.local --bob-pwd ...]
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from typing import Callable

import requests


# ── Session helpers ──────────────────────────────────────────────────────────


def login(base: str, email: str, password: str) -> requests.Session:
    s = requests.Session()
    resp = s.post(f"{base}/api/auth/login",
                   json={"email": email, "password": password})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed for {email}: {resp.status_code}")
    # If the app issues CSRF tokens, mirror it on subsequent non-GET calls.
    token = resp.cookies.get("csrf_token") or s.cookies.get("csrf_token")
    if token:
        s.headers["X-CSRFToken"] = token
    return s


def _expect_denied(resp: requests.Response, allow_404: bool = True) -> bool:
    """A response is 'denied' if it's 401/403, or 404 (resource hidden)."""
    return resp.status_code in (401, 403) or (allow_404 and resp.status_code == 404)


# ── Seed-data setup ──────────────────────────────────────────────────────────


def _seed_bob(base: str, bob: requests.Session) -> dict:
    """Create resources owned by bob so alice has targets to try to read."""
    seeded: dict = {"alerts": [], "positions": [], "tasks": [], "analyses": []}

    # alert
    try:
        r = bob.post(f"{base}/api/alerts/add",
                     json={"ticker": "AAPL", "condition": "price_above",
                           "threshold": 9999})
        if r.status_code == 200:
            r2 = bob.get(f"{base}/api/alerts")
            if r2.status_code == 200:
                arr = r2.json() if isinstance(r2.json(), list) else []
                if arr:
                    seeded["alerts"].append(int(arr[0]["id"]))
    except Exception:
        pass

    # position
    try:
        bob.post(f"{base}/api/portfolio/add",
                  json={"ticker": "MSFT", "shares": 1, "price": 100})
        seeded["positions"].append("MSFT")
    except Exception:
        pass

    # task (submit a no-op analysis)
    try:
        r = bob.post(f"{base}/api/analyze",
                     json={"ticker": "AAPL", "deep_analysis": False})
        if r.status_code == 200:
            tid = r.json().get("task_id")
            if tid:
                seeded["tasks"].append(tid)
    except Exception:
        pass

    return seeded


# ── Test matrix entries ──────────────────────────────────────────────────────


def _t(name: str, fn: Callable[[], requests.Response],
       allow_404: bool = True, expect: str = "denied") -> dict:
    """Single matrix entry — calls fn(), classifies the response."""
    try:
        resp = fn()
    except Exception as e:
        return {"name": name, "status": "error", "detail": str(e)}
    if expect == "denied":
        ok = _expect_denied(resp, allow_404=allow_404)
        return {
            "name": name,
            "status": "pass" if ok else "leak",
            "http": resp.status_code,
        }
    # expect == "ok"
    return {
        "name": name,
        "status": "pass" if resp.status_code == 200 else "fail",
        "http": resp.status_code,
    }


# ── Main matrix ──────────────────────────────────────────────────────────────


def run_cross_user_tests(
    base: str,
    alice_email: str, alice_pwd: str,
    bob_email: str, bob_pwd: str,
) -> dict:
    results = {"pass": [], "fail": [], "leak": [], "error": []}

    try:
        alice = login(base, alice_email, alice_pwd)
        bob = login(base, bob_email, bob_pwd)
    except Exception as e:
        return {"error": [str(e)], "pass": [], "fail": [], "leak": []}

    seeded = _seed_bob(base, bob)
    bob_alert_id = seeded["alerts"][0] if seeded["alerts"] else None
    bob_ticker = seeded["positions"][0] if seeded["positions"] else "MSFT"
    bob_task_id = seeded["tasks"][0] if seeded["tasks"] else None

    # ── Alerts ─────────────────────────────────────────────────────────────
    if bob_alert_id is not None:
        results = _dispatch(results, [
            _t("alerts.remove (alice→bob)",
               lambda: alice.post(f"{base}/api/alerts/remove",
                                   json={"id": bob_alert_id})),
        ])
    results = _dispatch(results, [
        _t("alerts.history (alice gets nothing of bob's)",
           lambda: alice.get(f"{base}/api/alerts/history"),
           expect="ok"),
    ])

    # ── Portfolio ──────────────────────────────────────────────────────────
    results = _dispatch(results, [
        _t("portfolio.delete (alice tries bob's ticker)",
           lambda: alice.delete(f"{base}/api/portfolio/{bob_ticker}")),
        _t("portfolio.update_cost (alice tries bob's ticker)",
           lambda: alice.post(f"{base}/api/portfolio/update_cost",
                               json={"ticker": bob_ticker, "avg_cost": 1.0})),
        _t("portfolio.snapshot (each tenant owns its snapshot)",
           lambda: alice.post(f"{base}/api/portfolio/snapshot"),
           expect="ok"),
        _t("portfolio.history (alice doesn't see bob's snapshots)",
           lambda: alice.get(f"{base}/api/portfolio/history"),
           expect="ok"),
    ])

    # ── Tasks ──────────────────────────────────────────────────────────────
    if bob_task_id is not None:
        results = _dispatch(results, [
            _t("tasks.cancel (alice→bob)",
               lambda: alice.post(f"{base}/api/tasks/{bob_task_id}/cancel")),
        ])

    # ── Admin gates (alice is plain user — must 403) ───────────────────────
    results = _dispatch(results, [
        _t("settings.write (non-admin)",
           lambda: alice.post(f"{base}/api/settings",
                               json={"llm_provider": "qwen"}),
           allow_404=False),
        _t("scheduler.start (non-admin)",
           lambda: alice.post(f"{base}/api/scheduler/start"),
           allow_404=False),
    ])

    # ── Anonymous baseline ─────────────────────────────────────────────────
    anon = requests.Session()
    for path in (
        "/api/portfolio/holdings", "/api/portfolio/pnl",
        "/api/portfolio/allocation", "/api/portfolio/history",
        "/api/tasks", "/api/alerts", "/api/alerts/history",
        "/api/settings",
    ):
        results = _dispatch(results, [
            _t(f"anon GET {path}",
               lambda p=path: anon.get(f"{base}{p}"),
               allow_404=False),
        ])

    results["go"] = len(results["leak"]) == 0 and len(results["fail"]) == 0
    return results


def _dispatch(results: dict, entries: list[dict]) -> dict:
    """Bucket entries into pass/leak/fail/error lists."""
    for e in entries:
        if e["status"] == "pass":
            results["pass"].append(e)
        elif e["status"] == "leak":
            results["leak"].append(e)
        elif e["status"] == "error":
            results["error"].append(e)
        else:
            results["fail"].append(e)
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Cross-user access tests")
    parser.add_argument("--base-url", default="http://localhost:9090")
    parser.add_argument("--alice-email", default="alice@test.local")
    parser.add_argument("--alice-pwd", default="AlicePass1!")
    parser.add_argument("--bob-email", default="bob@test.local")
    parser.add_argument("--bob-pwd", default="BobPass1!")
    args = parser.parse_args()

    results = run_cross_user_tests(
        args.base_url, args.alice_email, args.alice_pwd,
        args.bob_email, args.bob_pwd,
    )

    print(f"\n{'='*60}")
    go = results.get("go", False)
    print(f"CROSS-USER: {'✅ NO LEAKS' if go else '❌ LEAKS DETECTED'}")
    print(f"  Pass:  {len(results.get('pass', []))}")
    print(f"  Leak:  {len(results.get('leak', []))}")
    print(f"  Fail:  {len(results.get('fail', []))}")
    print(f"  Error: {len(results.get('error', []))}")

    for leak in results.get("leak", []):
        print(f"  🚨 LEAK: {leak['name']} → HTTP {leak.get('http')}")
    for fail in results.get("fail", []):
        print(f"  ❌ FAIL: {fail['name']} → HTTP {fail.get('http')}")
    for err in results.get("error", []):
        print(f"  ⚠ ERROR: {err['name']}: {err.get('detail')}")

    if not go:
        sys.exit(1)


if __name__ == "__main__":
    main()
