"""Shared fixtures for OAuth route tests.

Builds on the project-wide `app_client` fixture (see tests/conftest.py)
which already produces a multi-tenant DB + admin/alice/bob users. We add:

  * `oauth_app_client`     — sets OAUTH_ENCRYPT_KEY before app boot so the
                             startup fail-fast accepts the boot, and sets
                             both Google + GitHub credentials so the
                             provider list is non-empty. The
                             oauth_accounts migration is wired into
                             create_app() and already runs on the temp DB.
  * `mock_provider_factory` — patch shim that swaps both providers'
                             exchange_code with deterministic stand-ins.
                             Returns a small handle the tests use to
                             build (profile, tokens) responses.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from stock_trading_system.auth.oauth_providers import OAuthProfile, OAuthTokens


@pytest.fixture
def oauth_env(monkeypatch):
    """Set OAuth env *before* any app fixture so create_app sees it."""
    monkeypatch.setenv("OAUTH_ENCRYPT_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test_gid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test_gsec")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test_ghid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test_ghsec")
    return None


@pytest.fixture
def oauth_app_client(oauth_env, app_client):
    """Re-exports app_client but ensures OAuth env was set before boot.

    pytest fixture resolution is alphabetical-then-dependency, so naming
    the dependency `oauth_env` ahead of `app_client` is enough — but we
    declare both explicitly to make the order obvious.
    """
    return app_client


@dataclass
class FakeExchangeResult:
    profile: OAuthProfile
    tokens: OAuthTokens


def make_profile(*, sub: str, email: str | None = None,
                 verified: bool = True, name: str | None = None) -> OAuthProfile:
    return OAuthProfile(
        sub=sub, email=email, email_verified=verified,
        name=name, raw={"sub": sub, "email": email},
    )


def make_tokens(at: str = "at_test") -> OAuthTokens:
    return OAuthTokens(access_token=at, refresh_token="rt_test",
                       expires_at="2030-01-01T00:00:00")


@pytest.fixture
def patch_provider():
    """Helper context: stub a provider's exchange_code with a fixed result.

    Usage:
        with patch_provider("google", profile, tokens):
            client.get("/auth/oauth/google/callback?...")
    """

    @contextmanager
    def _ctx(provider: str, profile: OAuthProfile, tokens: OAuthTokens
             ) -> Iterator[None]:
        target_module = (
            "stock_trading_system.auth.oauth_providers."
            f"{'google' if provider == 'google' else 'github'}"
        )
        target_class = "GoogleProvider" if provider == "google" else "GitHubProvider"
        with patch(f"{target_module}.{target_class}.exchange_code",
                   return_value=(profile, tokens)):
            yield

    return _ctx


@pytest.fixture
def patch_provider_error():
    """Helper context: make a provider's exchange_code raise an error."""
    from stock_trading_system.auth.oauth_providers import OAuthExchangeError

    @contextmanager
    def _ctx(provider: str, msg: str = "boom") -> Iterator[None]:
        target_module = (
            "stock_trading_system.auth.oauth_providers."
            f"{'google' if provider == 'google' else 'github'}"
        )
        target_class = "GoogleProvider" if provider == "google" else "GitHubProvider"
        with patch(f"{target_module}.{target_class}.exchange_code",
                   side_effect=OAuthExchangeError(msg)):
            yield

    return _ctx
