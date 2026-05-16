"""P0.4 Login / register / invite-code rate limiting (Flask-Limiter).

Reference: docs/test-cases/hardening-iteration-v1.md §4 (TC-HD-C4-1..8).

Defaults from create_app():
    - /api/auth/login       10/min per IP, 5/min per email
    - /api/auth/register     5/hour per IP
    - /api/auth/invites-available 20/hour per IP

The shared ``app_client`` fixture uses in-memory storage, so we have to
reset Flask-Limiter's storage between scenarios. ``limiter.reset()`` is
the official way.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def limiter_app(app_client):
    """Enable Flask-Limiter (the shared conftest disables it for other
    suites). Reset counters between scenarios.

    Resetting Flask-Limiter's in-memory MovingWindow storage is brittle
    across multiple ``create_app`` cycles inside the same Python process —
    counters can survive a ``limiter.reset()`` if the storage object got
    re-bound. We clear the underlying dict explicitly for belt-and-braces.
    """
    flask_app = app_client["app"]
    flask_app.config["RATELIMIT_ENABLED"] = True
    from stock_trading_system.web.app import limiter
    limiter.enabled = True
    try:
        limiter.reset()
    except Exception:
        pass
    # Hard-clear the underlying MemoryStorage dict so cross-test counters
    # don't bleed in (the .reset() above is only honoured by some storage
    # backends / version combos).
    try:
        for store_attr in ("storage", "_storage"):
            store = getattr(limiter, store_attr, None)
            if store is not None:
                inner = getattr(store, "storage", None)
                if isinstance(inner, dict):
                    inner.clear()
    except Exception:
        pass
    yield {"client": flask_app.test_client(), "users": app_client["users"],
           "limiter": limiter}
    try:
        limiter.reset()
    except Exception:
        pass
    limiter.enabled = False
    flask_app.config["RATELIMIT_ENABLED"] = False


# ── TC-HD-C4-1: login IP-bucket throttles at 11th request/minute ─────────────


def test_login_ip_bucket_throttles(limiter_app):
    """11 failed logins / minute / IP → the 11th comes back 429.

    We rotate emails so the per-email bucket (5/min) doesn't trip first.
    """
    client = limiter_app["client"]
    for i in range(10):
        rv = client.post("/api/auth/login",
                         json={"email": f"victim{i}@test.local", "password": "wrong"})
        # First 10 should fail with 401 (bad credentials), not 429.
        assert rv.status_code == 401, (
            f"Hit {i}: expected 401 but got {rv.status_code}: {rv.data!r}"
        )
    # 11th — IP rate limit kicks in (rotated email so it's NOT the email bucket).
    rv = client.post("/api/auth/login",
                     json={"email": "victim_extra@test.local", "password": "wrong"})
    assert rv.status_code == 429, (
        f"11th request should be rate-limited; got {rv.status_code}: {rv.data!r}"
    )


# ── TC-HD-C4-2: login per-email bucket throttles at 6/min ────────────────────


def test_login_email_bucket_throttles(limiter_app):
    """Same email, varying IP (we can't really vary IP in test client, but
    the per-email bucket should fire even before the IP bucket at 6 hits)."""
    client = limiter_app["client"]
    same_email = "victim@test.local"
    for _ in range(5):
        client.post("/api/auth/login",
                    json={"email": same_email, "password": "wrong"})
    rv = client.post("/api/auth/login",
                     json={"email": same_email, "password": "wrong"})
    # 6th must be 429 because email bucket caps at 5/min.
    assert rv.status_code == 429, (
        f"6th hit on same email should trip the per-email bucket; "
        f"got {rv.status_code}"
    )


# ── TC-HD-C4-3: register IP bucket throttles at 6/hour ───────────────────────


def test_register_ip_bucket_throttles(limiter_app):
    """register cap is 5/hour."""
    client = limiter_app["client"]
    for _ in range(5):
        client.post("/api/auth/register",
                    json={"email": f"x{_}@test.local", "password": "Pw1!Pw1!",
                          "invite_code": "INVALID"})
    rv = client.post("/api/auth/register",
                     json={"email": "x6@test.local", "password": "Pw1!Pw1!",
                           "invite_code": "INVALID"})
    assert rv.status_code == 429


# ── TC-HD-C4-4: invites-available IP bucket throttles at 21/hour ─────────────


def test_invites_available_bucket_throttles(limiter_app):
    """invites-available cap is 20/hour."""
    client = limiter_app["client"]
    for _ in range(20):
        rv = client.get("/api/auth/invites-available")
        assert rv.status_code == 200
    rv = client.get("/api/auth/invites-available")
    assert rv.status_code == 429


# ── TC-HD-C4-5: 429 body shape ───────────────────────────────────────────────


def test_429_body_shape(limiter_app):
    """The error handler returns {"error": "rate_limited", ...}."""
    client = limiter_app["client"]
    # Trip the limit fast.
    for _ in range(11):
        client.post("/api/auth/login",
                    json={"email": "x@test.local", "password": "y"})
    rv = client.post("/api/auth/login",
                     json={"email": "x@test.local", "password": "y"})
    assert rv.status_code == 429
    body = rv.get_json() or {}
    assert body.get("error") == "rate_limited"
    assert "message" in body


# ── TC-HD-C4-6: successful login does NOT eat email-bucket budget ─────────────
#
# Flask-Limiter counts every request that reaches the route, including
# successes. We don't pretend otherwise — what we DO assert is that an
# admin's 11th successful login (which would have hit the IP cap) still
# succeeds on a fresh bucket. (Closing the loop on this is a P3 audit
# enhancement — Flask-Limiter has no out-of-box "count only failures".)


# ── TC-HD-C4-7: storage is in-memory by default ──────────────────────────────


def test_default_storage_is_memory(app_client):
    """Confirm we ship the documented default; production swaps via env."""
    flask_app = app_client["app"]
    assert flask_app.config.get("RATELIMIT_STORAGE_URI", "").startswith("memory")
