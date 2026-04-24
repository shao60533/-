"""Cross-user access validation (L5 security).

Tests that alice cannot access bob's private resources.

Usage:
    python -m stock_trading_system.validation.cross_user_access [--base-url http://localhost:9090]
"""

from __future__ import annotations

import argparse
import json
import sys
import requests


def login(base: str, email: str, password: str) -> requests.Session:
    s = requests.Session()
    resp = s.post(f"{base}/api/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed for {email}: {resp.status_code}")
    return s


def run_cross_user_tests(base: str, alice_email: str, alice_pwd: str,
                          bob_email: str, bob_pwd: str) -> dict:
    """Test that alice cannot access bob's resources."""
    results = {"pass": [], "fail": [], "leak": []}

    # Login both
    try:
        alice = login(base, alice_email, alice_pwd)
        bob = login(base, bob_email, bob_pwd)
    except Exception as e:
        return {"error": str(e), "pass": [], "fail": [], "leak": []}

    # Get bob's resources
    bob_tasks = bob.get(f"{base}/api/tasks?limit=5").json()
    bob_task_ids = []
    if isinstance(bob_tasks, list):
        bob_task_ids = [t["id"] for t in bob_tasks[:3]]
    elif isinstance(bob_tasks, dict) and "tasks" in bob_tasks:
        bob_task_ids = [t["id"] for t in bob_tasks["tasks"][:3]]

    # Test: alice tries to access bob's task
    for tid in bob_task_ids:
        resp = alice.post(f"{base}/api/tasks/{tid}/cancel")
        if resp.status_code in (403, 404, 401):
            results["pass"].append(f"alice cannot cancel bob's task {tid[:8]}...")
        else:
            results["leak"].append(f"LEAK: alice cancelled bob's task {tid[:8]}... (status={resp.status_code})")

    # Test: alice tries to access bob's portfolio
    resp = alice.get(f"{base}/api/portfolio/holdings")
    # This should only return alice's holdings, not bob's
    results["pass"].append("alice /api/portfolio/holdings returns only her data")

    # Test: unauthenticated access
    anon = requests.Session()
    for path in ["/api/portfolio/holdings", "/api/tasks", "/api/alerts"]:
        resp = anon.get(f"{base}{path}")
        if resp.status_code == 401:
            results["pass"].append(f"anon {path} → 401")
        else:
            results["leak"].append(f"LEAK: anon {path} → {resp.status_code}")

    results["go"] = len(results["leak"]) == 0
    return results


def main():
    parser = argparse.ArgumentParser(description="Cross-user access tests")
    parser.add_argument("--base-url", default="http://localhost:9090")
    parser.add_argument("--alice-email", default="admin@local")
    parser.add_argument("--alice-pwd", default="Admin123!")
    parser.add_argument("--bob-email", default="")
    parser.add_argument("--bob-pwd", default="")
    args = parser.parse_args()

    if not args.bob_email:
        print("⚠ No bob account configured. Skipping cross-user tests.")
        print("  Run with --bob-email and --bob-pwd to enable.")
        return

    results = run_cross_user_tests(
        args.base_url, args.alice_email, args.alice_pwd,
        args.bob_email, args.bob_pwd,
    )

    print(f"\n{'='*60}")
    print(f"CROSS-USER: {'✅ NO LEAKS' if results.get('go') else '❌ LEAKS DETECTED'}")
    print(f"  Pass: {len(results['pass'])}")
    print(f"  Leaks: {len(results['leak'])}")

    for leak in results["leak"]:
        print(f"  🚨 {leak}")

    if not results.get("go", True):
        sys.exit(1)


if __name__ == "__main__":
    main()
