"""Tests for /auth/oauth/<provider>/start + /auth/oauth/<provider>/callback.

The 5-branch callback dispatch (state check → link binding → bound login →
auto-merge → unverified hint → register handoff) is the single highest-risk
surface in v1.0; these 12 tests pin down each branch.
"""

from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from stock_trading_system.auth.oauth_repository import OAuthAccountRepository

from tests.auth.conftest import make_profile, make_tokens


# ── /auth/oauth/<provider>/start ─────────────────────────────────────────────


def test_start_unknown_provider_redirects_with_error(oauth_app_client):
    c = oauth_app_client["make_client"]()
    r = c.get("/auth/oauth/twitter/start", follow_redirects=False)
    assert r.status_code == 302
    assert "/login?error=unknown_provider" in r.location


def test_start_redirects_to_provider_with_state_and_pkce(oauth_app_client):
    c = oauth_app_client["make_client"]()
    r = c.get("/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code == 302
    parsed = urlparse(r.location)
    assert parsed.netloc == "accounts.google.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test_gid"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "state" in qs and len(qs["state"][0]) >= 32
    # session must hold the verifier so callback can re-supply it.
    with c.session_transaction() as sess:
        assert sess["oauth_state"] == qs["state"][0]
        assert sess["oauth_provider"] == "google"
        assert sess["oauth_intent"] == "login"
        assert len(sess["oauth_code_verifier"]) > 50


# ── /auth/oauth/<provider>/callback — branch 1: state guard ──────────────────


def test_callback_state_mismatch_rejects(oauth_app_client):
    c = oauth_app_client["make_client"]()
    # Prime session with one state; send a different one in querystring.
    c.get("/auth/oauth/google/start")
    r = c.get("/auth/oauth/google/callback?state=evil&code=anything",
              follow_redirects=False)
    assert r.status_code == 302
    assert "/login?error=state_mismatch" in r.location


def test_callback_missing_code_rejects(oauth_app_client):
    c = oauth_app_client["make_client"]()
    c.get("/auth/oauth/google/start")
    with c.session_transaction() as sess:
        state = sess["oauth_state"]
    r = c.get(f"/auth/oauth/google/callback?state={state}",  # no code
              follow_redirects=False)
    assert r.status_code == 302
    assert "/login?error=no_code" in r.location


def test_callback_exchange_failure_redirects_with_error(
    oauth_app_client, patch_provider_error,
):
    c = oauth_app_client["make_client"]()
    c.get("/auth/oauth/google/start")
    with c.session_transaction() as sess:
        state = sess["oauth_state"]
    with patch_provider_error("google"):
        r = c.get(f"/auth/oauth/google/callback?state={state}&code=abc",
                  follow_redirects=False)
    assert r.status_code == 302
    assert "/login?error=exchange_failed" in r.location


# ── Helpers for branches 2-5 ─────────────────────────────────────────────────


def _start_and_callback(client, provider, profile, tokens, patch_ctx,
                        intent="login", next_url="/"):
    """Drive a /start → /callback sequence and return the callback response."""
    qs = ""
    if intent and intent != "login":
        qs += f"?intent={intent}"
    if next_url and next_url != "/":
        sep = "&" if qs else "?"
        qs += f"{sep}next={next_url}"
    client.get(f"/auth/oauth/{provider}/start{qs}")
    with client.session_transaction() as sess:
        state = sess["oauth_state"]
    with patch_ctx(provider, profile, tokens):
        return client.get(
            f"/auth/oauth/{provider}/callback?state={state}&code=abc",
            follow_redirects=False,
        )


# ── Branch 3: provider already bound → direct login ──────────────────────────


def test_callback_existing_oauth_link_logs_user_in(
    oauth_app_client, patch_provider,
):
    """alice already has oauth_accounts row → instant login, no register."""
    db_path = oauth_app_client["db_path"]
    alice = oauth_app_client["users"].alice

    # Pre-seed oauth_accounts for alice.
    repo = OAuthAccountRepository(db_path)
    from stock_trading_system.auth.oauth_repository import (
        OAuthProfileRecord, OAuthTokenRecord,
    )
    repo.upsert(
        user_id=alice.id, provider="google",
        profile=OAuthProfileRecord(
            sub="goog_existing", email=alice.email, email_verified=True, raw={},
        ),
        tokens=OAuthTokenRecord(
            access_token="old_at", refresh_token=None, expires_at=None,
        ),
    )

    c = oauth_app_client["make_client"]()
    profile = make_profile(sub="goog_existing", email=alice.email)
    r = _start_and_callback(c, "google", profile, make_tokens(), patch_provider)

    assert r.status_code == 302
    assert r.location.endswith("/")
    # Session must now carry user_id pointing at alice.
    with c.session_transaction() as sess:
        assert sess.get("user_id") == alice.id


# ── Branch 4a: email exists + verified → auto-merge ──────────────────────────


def test_callback_auto_merge_when_provider_verified(oauth_app_client, patch_provider):
    alice_email = oauth_app_client["users"].alice.email
    alice_id = oauth_app_client["users"].alice.id

    c = oauth_app_client["make_client"]()
    profile = make_profile(sub="goog_new", email=alice_email, verified=True)
    r = _start_and_callback(c, "google", profile, make_tokens(), patch_provider)

    assert r.status_code == 302
    assert r.location.endswith("/")
    with c.session_transaction() as sess:
        assert sess.get("user_id") == alice_id

    # oauth_accounts row created and linked to alice.
    db = oauth_app_client["db_path"]
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT user_id, provider FROM oauth_accounts "
            "WHERE provider_user_id=?", ("goog_new",),
        ).fetchone()
    assert row == (alice_id, "google")


# ── Branch 4b: email exists but provider unverified → no merge ──────────────


def test_callback_unverified_email_blocks_auto_merge(oauth_app_client, patch_provider):
    alice_email = oauth_app_client["users"].alice.email

    c = oauth_app_client["make_client"]()
    profile = make_profile(sub="gh_unverified", email=alice_email, verified=False)
    r = _start_and_callback(c, "github", profile, make_tokens(), patch_provider)

    assert r.status_code == 302
    assert "/login?notice=email_unverified_link" in r.location
    assert "provider=github" in r.location
    # NOT logged in.
    with c.session_transaction() as sess:
        assert "user_id" not in sess
    # oauth_accounts row NOT created.
    db = oauth_app_client["db_path"]
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT 1 FROM oauth_accounts WHERE provider_user_id=?",
            ("gh_unverified",),
        ).fetchone()
    assert row is None


# ── Branch 5: brand-new email → /register handoff with pending payload ──────


def test_callback_brand_new_email_redirects_to_register(
    oauth_app_client, patch_provider,
):
    c = oauth_app_client["make_client"]()
    profile = make_profile(sub="goog_new_user", email="new@x.com",
                           verified=True, name="Newbie")
    r = _start_and_callback(c, "google", profile, make_tokens(), patch_provider)

    assert r.status_code == 302
    parsed = urlparse(r.location)
    assert parsed.path == "/register"
    qs = parse_qs(parsed.query)
    assert qs["provider"] == ["google"]
    assert qs["email"] == ["new@x.com"]
    assert "pending" in qs and len(qs["pending"][0]) > 20  # signed token
    # NOT yet logged in.
    with c.session_transaction() as sess:
        assert "user_id" not in sess


# ── Branch 2: intent=link binding (logged-in user adds a provider) ──────────


def test_callback_link_intent_requires_login(oauth_app_client, patch_provider):
    c = oauth_app_client["make_client"]()  # anon
    profile = make_profile(sub="goog_x", email="any@x.com")
    r = _start_and_callback(c, "google", profile, make_tokens(),
                            patch_provider, intent="link")
    # enforce_auth doesn't intercept /auth/oauth/* (it's PUBLIC), so the
    # callback handler itself must reject link-without-login.
    assert r.status_code == 302
    assert "/login?error=link_requires_login" in r.location


def test_callback_link_intent_binds_to_current_user(
    oauth_app_client, patch_provider,
):
    users = oauth_app_client["users"]
    c = oauth_app_client["make_client"](users.alice_email, users.alice_password)

    profile = make_profile(sub="goog_link", email="alt@x.com", verified=True)
    r = _start_and_callback(c, "google", profile, make_tokens(),
                            patch_provider, intent="link")
    assert r.status_code == 302
    assert "linked=google" in r.location
    # still alice in session.
    with c.session_transaction() as sess:
        assert sess.get("user_id") == users.alice.id

    db = oauth_app_client["db_path"]
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT user_id FROM oauth_accounts WHERE provider_user_id=?",
            ("goog_link",),
        ).fetchone()
    assert row[0] == users.alice.id


def test_callback_link_intent_rejects_when_provider_taken(
    oauth_app_client, patch_provider,
):
    """If the OAuth account already binds to another internal user, refuse."""
    users = oauth_app_client["users"]

    # alice has goog_taken bound first.
    repo = OAuthAccountRepository(oauth_app_client["db_path"])
    from stock_trading_system.auth.oauth_repository import (
        OAuthProfileRecord, OAuthTokenRecord,
    )
    repo.upsert(
        user_id=users.alice.id, provider="google",
        profile=OAuthProfileRecord(sub="goog_taken", email="alt@x.com",
                                   email_verified=True, raw={}),
        tokens=OAuthTokenRecord(access_token="at", refresh_token=None,
                                expires_at=None),
    )

    # bob logs in and tries to link the SAME google account.
    c = oauth_app_client["make_client"](users.bob_email, users.bob_password)
    profile = make_profile(sub="goog_taken", email="alt@x.com")
    r = _start_and_callback(c, "google", profile, make_tokens(),
                            patch_provider, intent="link")
    assert r.status_code == 302
    assert "/settings?error=oauth_taken" in r.location

    # bob's user did NOT get the row.
    with sqlite3.connect(oauth_app_client["db_path"]) as conn:
        row = conn.execute(
            "SELECT user_id FROM oauth_accounts WHERE provider_user_id=?",
            ("goog_taken",),
        ).fetchone()
    assert row[0] == users.alice.id


# ── Multi-tenant isolation: bob's bound provider must NOT log alice in ──────


def test_callback_multitenant_isolation(oauth_app_client, patch_provider):
    """Ensure (provider, sub) UNIQUE keeps bob's google identity out of alice."""
    users = oauth_app_client["users"]
    repo = OAuthAccountRepository(oauth_app_client["db_path"])
    from stock_trading_system.auth.oauth_repository import (
        OAuthProfileRecord, OAuthTokenRecord,
    )
    repo.upsert(
        user_id=users.bob.id, provider="google",
        profile=OAuthProfileRecord(
            sub="goog_bob", email=users.bob.email,
            email_verified=True, raw={},
        ),
        tokens=OAuthTokenRecord(access_token="at", refresh_token=None,
                                expires_at=None),
    )
    c = oauth_app_client["make_client"]()  # anon
    profile = make_profile(sub="goog_bob", email=users.bob.email)
    r = _start_and_callback(c, "google", profile, make_tokens(), patch_provider)

    # Logs in as bob — NEVER as alice.
    assert r.status_code == 302
    with c.session_transaction() as sess:
        assert sess.get("user_id") == users.bob.id
        assert sess.get("user_id") != users.alice.id
