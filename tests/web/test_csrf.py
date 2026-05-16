"""P0.1 CSRF protection — Flask-WTF CSRFProtect is wired in and intercepts
state-changing requests that don't carry a token, while exempt endpoints
(/api/auth/login, /api/auth/register, /api/auth/oauth/register) stay
reachable pre-session.

Reference: docs/test-cases/hardening-iteration-v1.md §1 (TC-HD-C1-1 .. C1-12).
"""

from __future__ import annotations

import pytest


# ── Fixture: a Flask client that keeps CSRF enabled ──────────────────────────


@pytest.fixture
def csrf_enabled_client(app_client):
    """Re-enables CSRFProtect on the shared test app and returns a client.

    The shared ``app_client`` fixture disables CSRF so business-logic suites
    can keep using plain ``client.post(...)``. Here we explicitly want the
    protection active so we can assert the contract.
    """
    flask_app = app_client["app"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    client = flask_app.test_client()
    yield {"client": client, "users": app_client["users"], "login": app_client["login"]}
    flask_app.config["WTF_CSRF_ENABLED"] = False


def _get_csrf_token(flask_app):
    """Generate a CSRF token in a request context that has a session."""
    from flask_wtf.csrf import generate_csrf
    with flask_app.test_request_context():
        return generate_csrf()


# ── TC-HD-C1-1 .. C1-3: CSRFProtect initialized ──────────────────────────────


def test_csrf_extension_registered(app_client):
    """CSRFProtect must be installed on the app."""
    flask_app = app_client["app"]
    assert "csrf" in flask_app.extensions, (
        "Flask-WTF CSRFProtect must be initialized in create_app(). "
        "Found extensions: %s" % list(flask_app.extensions.keys())
    )


def test_csrf_time_limit_disabled(app_client):
    """Token must outlive the session so users with 30-day sessions don't
    get challenged mid-task. design §3.1 P0.1."""
    flask_app = app_client["app"]
    assert flask_app.config.get("WTF_CSRF_TIME_LIMIT") is None


# ── TC-HD-C1-4 .. C1-9: sensitive POST/DELETE require token ──────────────────


def _post_no_token(csrf_app, path, json_body=None):
    """POST without a token — must be rejected."""
    return csrf_app["client"].post(path, json=(json_body or {}))


def test_csrf_blocks_alerts_remove_without_token(csrf_enabled_client):
    """TC-HD-C1-5: POST /api/alerts/remove without CSRF token is 400."""
    # Need to be logged in first (the route requires auth) — but login is
    # exempt, so we can do that without a token.
    users = csrf_enabled_client["users"]
    csrf_enabled_client["login"](
        csrf_enabled_client["client"], users.alice_email, users.alice_password
    )
    rv = _post_no_token(csrf_enabled_client, "/api/alerts/remove", {"id": 1})
    assert rv.status_code == 400, (
        f"Expected 400 (CSRF blocked) but got {rv.status_code}. "
        f"Body: {rv.data!r}"
    )


def test_csrf_blocks_settings_post_without_token(csrf_enabled_client):
    """TC-HD-C1-6: POST /api/settings without CSRF token is 400."""
    users = csrf_enabled_client["users"]
    csrf_enabled_client["login"](
        csrf_enabled_client["client"],
        users.admin_email, users.admin_password,
    )
    rv = _post_no_token(csrf_enabled_client, "/api/settings", {"foo": "bar"})
    assert rv.status_code == 400


def test_csrf_blocks_scheduler_start_without_token(csrf_enabled_client):
    """TC-HD-C1-7: POST /api/scheduler/start without CSRF token is 400."""
    users = csrf_enabled_client["users"]
    csrf_enabled_client["login"](
        csrf_enabled_client["client"],
        users.admin_email, users.admin_password,
    )
    rv = _post_no_token(csrf_enabled_client, "/api/scheduler/start", {})
    assert rv.status_code == 400


def test_csrf_blocks_portfolio_delete_without_token(csrf_enabled_client):
    """TC-HD-C1-9: DELETE /api/portfolio/<ticker> without CSRF token is 400."""
    users = csrf_enabled_client["users"]
    csrf_enabled_client["login"](
        csrf_enabled_client["client"], users.alice_email, users.alice_password
    )
    rv = csrf_enabled_client["client"].delete("/api/portfolio/AAPL")
    assert rv.status_code == 400


# ── TC-HD-C1-10 .. C1-12: exempt routes still work without a token ───────────


def test_login_exempt_from_csrf(csrf_enabled_client):
    """TC-HD-C1-10: /api/auth/login accepts POST without CSRF token.

    Pre-login users have no session, so they can't have a token. Login must
    be exempt, otherwise the system is unbootstrappable.
    """
    users = csrf_enabled_client["users"]
    rv = csrf_enabled_client["client"].post(
        "/api/auth/login",
        json={"email": users.alice_email, "password": users.alice_password},
    )
    # Either 200 (success) or 401 (wrong creds) is fine — what we're asserting
    # is that CSRF *isn't* the gate here.
    assert rv.status_code != 400, (
        f"Login must be CSRF-exempt; got 400. Body: {rv.data!r}"
    )


def test_register_exempt_from_csrf(csrf_enabled_client):
    """TC-HD-C1-11: /api/auth/register accepts POST without CSRF token."""
    rv = csrf_enabled_client["client"].post(
        "/api/auth/register",
        json={"email": "new@test.local", "password": "Whatever1!",
              "invite_code": "INVALID"},
    )
    # 400 with error="invite_code" body is the business-layer rejection.
    # What we don't want: 400 from CSRF before the business code runs.
    assert rv.status_code == 400
    body = rv.get_json() or {}
    assert body.get("error") != "csrf_failed"


def test_oauth_register_exempt_from_csrf(csrf_enabled_client):
    """TC-HD-C1-12 (subset): /api/auth/oauth/register accepts POST without CSRF token.

    Same reason as login — pre-session third-party redirect flow.
    """
    rv = csrf_enabled_client["client"].post(
        "/api/auth/oauth/register",
        json={"pending_token": "anything", "invite_code": "INVALID"},
    )
    # Body validation will reject (400 / 401) but not via CSRF.
    assert rv.status_code != 200  # business code runs (it should reject)
    body = rv.get_json() or {}
    assert "CSRF" not in str(body).upper()


# ── Bonus: confirm the meta tag now renders a real token ─────────────────────


def test_meta_csrf_token_renders(app_client):
    """The layout.html meta name="csrf-token" must produce a non-empty value
    once CSRFProtect is initialized so the front-end api.ts can read it.

    login.html / register.html are standalone HTML (not extending layout) —
    they're exempt anyway. We assert via a page that does extend layout.
    """
    flask_app = app_client["app"]
    users = app_client["users"]
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = flask_app.test_client()
        # Need a logged-in client to hit a layout-extending page.
        client.post("/api/auth/login",
                    json={"email": users.alice_email, "password": users.alice_password})
        rv = client.get("/")
        assert rv.status_code in (200, 302), (
            f"Root page should render or redirect; got {rv.status_code}"
        )
        if rv.status_code == 302:
            rv = client.get(rv.headers["Location"])
        body = rv.data.decode("utf-8")
        import re
        m = re.search(r'meta name="csrf-token" content="([^"]*)"', body)
        assert m is not None, "layout.html should render the csrf meta tag"
        token = m.group(1)
        assert token, "csrf_token() must be defined and non-empty"
        assert len(token) >= 16
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = False
