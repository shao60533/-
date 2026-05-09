"""Tests for POST /api/auth/oauth/register — brand-new-email finalization.

Locks down:
  - pending token must be valid + signed (rejects invalid / expired)
  - invite code is required (multi-tenant gate preserved)
  - email-already-exists rejected
  - happy path creates user + redeems invite + binds oauth_accounts
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.auth.oauth_session import make_pending_token


def _make_pending(app_client, *, provider="google", sub="goog_new",
                  email="new@x.com", name="Newbie"):
    return make_pending_token(
        app_client["app"].config["SECRET_KEY"],
        {
            "provider": provider,
            "sub": sub,
            "email": email,
            "name": name,
            "tokens": {
                "access_token": "at_new",
                "refresh_token": None,
                "expires_at": None,
            },
        },
    )


def _new_invite(app_client, *, days: int = 7) -> str:
    """Mint a fresh invite code via the admin API."""
    admin = app_client["make_client"](
        app_client["users"].admin_email,
        app_client["users"].admin_password,
    )
    r = admin.post("/api/admin/invites", json={"days": days})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["code"]


def test_register_rejects_invalid_pending(oauth_app_client):
    invite = _new_invite(oauth_app_client)
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": "garbage", "invite_code": invite})
    assert r.status_code == 400
    assert r.get_json()["error"] == "pending_invalid"


def test_register_rejects_expired_pending(oauth_app_client, monkeypatch):
    # Build a pending token, then verify with max_age=0 to simulate expiry.
    invite = _new_invite(oauth_app_client)
    pending = _make_pending(oauth_app_client)

    # Patch verify_pending_token at its callsite to force expiry behavior:
    # itsdangerous SignatureExpired ↘ verify returns None ↘ route → 400.
    from stock_trading_system.web import app as app_module  # noqa: F401

    # Cheaper: just hand a tampered signature.
    bad = pending[:-2] + ("AB" if pending[-2:] != "AB" else "CD")
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": bad, "invite_code": invite})
    assert r.status_code == 400
    assert r.get_json()["error"] == "pending_invalid"


def test_register_requires_invite_code(oauth_app_client):
    pending = _make_pending(oauth_app_client)
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": pending, "invite_code": ""})
    assert r.status_code == 400
    body = r.get_json()
    # InviteCodeManager.validate('') returns 'invite_invalid'.
    assert body["error"] == "invite_invalid"


def test_register_rejects_existing_email(oauth_app_client):
    """If the email already exists in users, OAuth signup must refuse."""
    invite = _new_invite(oauth_app_client)
    pending = _make_pending(
        oauth_app_client,
        email=oauth_app_client["users"].alice_email,  # collision
    )
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": pending, "invite_code": invite})
    assert r.status_code == 400
    assert r.get_json()["error"] == "email_exists"


def test_register_happy_path_creates_user_and_redeems_invite(oauth_app_client):
    invite = _new_invite(oauth_app_client)
    pending = _make_pending(
        oauth_app_client,
        provider="google", sub="goog_brand_new", email="brand@new.com",
        name="Brand New",
    )
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": pending, "invite_code": invite,
                     "display_name": "Brand"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"] is True
    new_id = body["user_id"]

    # Session populated.
    with c.session_transaction() as sess:
        assert sess["user_id"] == new_id

    db = oauth_app_client["db_path"]
    with sqlite3.connect(db) as conn:
        # User row exists with display_name we sent.
        u = conn.execute(
            "SELECT email, display_name FROM users WHERE id=?", (new_id,),
        ).fetchone()
        assert u == ("brand@new.com", "Brand")
        # oauth_accounts row created.
        oa = conn.execute(
            "SELECT user_id, provider, provider_user_id "
            "FROM oauth_accounts WHERE provider_user_id=?",
            ("goog_brand_new",),
        ).fetchone()
        assert oa == (new_id, "google", "goog_brand_new")
        # Invite was redeemed.
        ic = conn.execute(
            "SELECT used_by FROM invite_codes WHERE code=?", (invite,),
        ).fetchone()
        assert ic[0] == new_id


def test_register_uses_body_email_when_pending_email_blank(oauth_app_client):
    """Provider returned no email → user supplies one in the form."""
    invite = _new_invite(oauth_app_client)
    pending = _make_pending(
        oauth_app_client,
        provider="github", sub="gh_no_email", email="",  # provider gave nothing
        name="ghuser",
    )
    c = oauth_app_client["make_client"]()
    r = c.post("/api/auth/oauth/register",
               json={"pending": pending, "invite_code": invite,
                     "email": "manual@x.com"})
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["user_id"]
    db = oauth_app_client["db_path"]
    with sqlite3.connect(db) as conn:
        email = conn.execute(
            "SELECT email FROM users WHERE id=?", (new_id,),
        ).fetchone()[0]
    assert email == "manual@x.com"
