"""Tests for /api/auth/oauth/<provider>/unlink + /api/auth/oauth/linked.

Locks down:
  - unlink requires authentication
  - unlink succeeds when bound; idempotent failure when not bound
  - linked endpoint reflects current state (provider list + has_password)
"""

from __future__ import annotations

import pytest

from stock_trading_system.auth.oauth_repository import (
    OAuthAccountRepository,
    OAuthProfileRecord,
    OAuthTokenRecord,
)


def _seed_link(db_path: str, user_id: int, provider: str, sub: str) -> None:
    repo = OAuthAccountRepository(db_path)
    repo.upsert(
        user_id=user_id, provider=provider,
        profile=OAuthProfileRecord(sub=sub, email="x@y.com",
                                   email_verified=True, raw={}),
        tokens=OAuthTokenRecord(access_token="at", refresh_token=None,
                                expires_at=None),
    )


def test_unlink_requires_authentication(oauth_app_client):
    c = oauth_app_client["make_client"]()  # anon
    r = c.post("/api/auth/oauth/google/unlink")
    assert r.status_code == 401


def test_unlink_returns_404_when_not_linked(oauth_app_client):
    users = oauth_app_client["users"]
    c = oauth_app_client["make_client"](users.alice_email, users.alice_password)
    # alice has no oauth links yet.
    r = c.post("/api/auth/oauth/google/unlink")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_linked"


def test_unlink_succeeds_when_bound(oauth_app_client):
    users = oauth_app_client["users"]
    _seed_link(oauth_app_client["db_path"], users.alice.id, "google", "goog_a")

    c = oauth_app_client["make_client"](users.alice_email, users.alice_password)
    # Sanity: linked endpoint reports the binding first.
    r = c.get("/api/auth/oauth/linked")
    assert r.status_code == 200
    assert any(p["provider"] == "google" for p in r.get_json()["providers"])

    r = c.post("/api/auth/oauth/google/unlink")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    # Now empty.
    r = c.get("/api/auth/oauth/linked")
    assert r.get_json()["providers"] == []


def test_linked_endpoint_reflects_two_providers(oauth_app_client):
    users = oauth_app_client["users"]
    _seed_link(oauth_app_client["db_path"], users.bob.id, "google", "goog_b")
    _seed_link(oauth_app_client["db_path"], users.bob.id, "github", "gh_b")

    c = oauth_app_client["make_client"](users.bob_email, users.bob_password)
    r = c.get("/api/auth/oauth/linked")
    body = r.get_json()
    assert body["has_password"] is True
    names = {p["provider"] for p in body["providers"]}
    assert names == {"google", "github"}
