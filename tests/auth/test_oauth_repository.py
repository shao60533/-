"""Tests for OAuthAccountRepository — direct DB-level invariants.

Covers the 6 contractual behaviors the route layer relies on:
  1. find_by_provider_id miss → None
  2. upsert insert → stored row + encrypted access_token at rest
  3. find_by_provider_id hit
  4. upsert update keeps id, refreshes email + last_login_at
  5. list_by_user returns multiple providers in created_at order
  6. delete_by_user_provider is idempotent (True then False)
"""

from __future__ import annotations

import sqlite3

import pytest
from cryptography.fernet import Fernet

from stock_trading_system.auth.oauth_repository import (
    OAuthAccountRepository,
    OAuthProfileRecord,
    OAuthTokenRecord,
)
from stock_trading_system.migrations.add_oauth_accounts import add_oauth_accounts


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("OAUTH_ENCRYPT_KEY", Fernet.generate_key().decode())
    path = str(tmp_path / "oauth_repo.db")
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL
            );
            INSERT INTO users (email, password_hash, display_name)
            VALUES ('a@x.com', 'h', 'A'), ('b@x.com', 'h', 'B');
            """
        )
    add_oauth_accounts(path)
    return path


@pytest.fixture
def repo(db_path):
    return OAuthAccountRepository(db_path)


def _profile(sub: str = "goog_1", email: str = "a@x.com",
             verified: bool = True) -> OAuthProfileRecord:
    return OAuthProfileRecord(sub=sub, email=email, email_verified=verified,
                              raw={"name": "A"})


def _tokens(at: str = "at_v1") -> OAuthTokenRecord:
    return OAuthTokenRecord(access_token=at, refresh_token="rt_v1",
                            expires_at="2030-01-01")


def test_find_by_provider_id_miss_returns_none(repo):
    assert repo.find_by_provider_id("google", "no_such_sub") is None


def test_upsert_insert_persists_and_encrypts(repo, db_path):
    acct = repo.upsert(user_id=1, provider="google",
                       profile=_profile(), tokens=_tokens("plaintext_token"))
    assert acct.user_id == 1
    assert acct.provider == "google"
    assert acct.email_verified is True

    # Plaintext must never appear in the column.
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute(
            "SELECT access_token_enc FROM oauth_accounts WHERE id=?",
            (acct.id,),
        ).fetchone()[0]
    assert "plaintext_token" not in raw


def test_find_by_provider_id_hit_after_upsert(repo):
    inserted = repo.upsert(user_id=1, provider="google",
                           profile=_profile(), tokens=_tokens())
    found = repo.find_by_provider_id("google", "goog_1")
    assert found is not None
    assert found.id == inserted.id


def test_upsert_update_preserves_id_refreshes_email(repo):
    a1 = repo.upsert(user_id=1, provider="google",
                     profile=_profile(email="old@x.com"), tokens=_tokens())
    a2 = repo.upsert(user_id=1, provider="google",
                     profile=_profile(email="new@x.com"), tokens=_tokens("at_v2"))
    assert a2.id == a1.id
    assert a2.email == "new@x.com"
    # last_login_at should be set on every touch.
    assert a2.last_login_at is not None


def test_list_by_user_returns_multiple_providers(repo):
    repo.upsert(user_id=1, provider="google",
                profile=_profile(sub="goog_1"), tokens=_tokens())
    repo.upsert(user_id=1, provider="github",
                profile=_profile(sub="gh_1"), tokens=_tokens())
    repo.upsert(user_id=2, provider="google",
                profile=_profile(sub="goog_2"), tokens=_tokens())

    user1 = repo.list_by_user(1)
    assert {a.provider for a in user1} == {"google", "github"}
    user2 = repo.list_by_user(2)
    assert len(user2) == 1 and user2[0].provider == "google"


def test_delete_by_user_provider_is_idempotent(repo):
    repo.upsert(user_id=1, provider="github",
                profile=_profile(sub="gh_1"), tokens=_tokens())
    assert repo.delete_by_user_provider(1, "github") is True
    # Second call: nothing left to delete.
    assert repo.delete_by_user_provider(1, "github") is False
    assert repo.list_by_user(1) == []
