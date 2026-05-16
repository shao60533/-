"""Onboarding init on register (v1.0).

Both /api/auth/register and /api/auth/oauth/register must call
OnboardingRepository.init_for_new_user, so the welcome modal fires on
the user's first dashboard visit.
"""

from __future__ import annotations

import sqlite3

import pytest
from cryptography.fernet import Fernet

from stock_trading_system.auth.oauth_session import make_pending_token


@pytest.fixture
def oauth_register_env(monkeypatch):
    """Set OAuth env before any app fixture boots so create_app() accepts it."""
    monkeypatch.setenv("OAUTH_ENCRYPT_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test_gid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test_gsec")


def _new_invite(app_client) -> str:
    admin = app_client["make_client"](
        app_client["users"].admin_email,
        app_client["users"].admin_password,
    )
    r = admin.post("/api/admin/invites", json={"days": 7})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["code"]


def _welcome_pending(db_path: str, user_id: int) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT welcome_pending FROM user_onboarding WHERE user_id=?",
            (user_id,),
        ).fetchone()
    assert row is not None, "user_onboarding row should exist after register"
    return int(row[0])


def test_email_register_sets_welcome_pending(app_client):
    invite = _new_invite(app_client)
    c = app_client["make_client"]()
    r = c.post(
        "/api/auth/register",
        json={
            "invite_code": invite,
            "email": "fresh@x.com",
            "password": "FreshPass1!",
            "display_name": "Fresh",
        },
    )
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["user"]["id"]
    assert _welcome_pending(app_client["db_path"], new_id) == 1


def test_oauth_register_sets_welcome_pending(oauth_register_env, app_client):
    invite = _new_invite(app_client)
    pending = make_pending_token(
        app_client["app"].config["SECRET_KEY"],
        {
            "provider": "google",
            "sub": "goog_obfresh",
            "email": "obfresh@x.com",
            "name": "OB Fresh",
            "tokens": {"access_token": "at", "refresh_token": None,
                       "expires_at": None},
        },
    )
    c = app_client["make_client"]()
    r = c.post(
        "/api/auth/oauth/register",
        json={"pending": pending, "invite_code": invite,
              "display_name": "OB Fresh"},
    )
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["user_id"]
    assert _welcome_pending(app_client["db_path"], new_id) == 1
