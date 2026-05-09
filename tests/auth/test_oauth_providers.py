"""Tests for OAuth provider implementations (Google + GitHub).

Provider-level tests are isolated from Flask: every external HTTP call is
mocked. The aim is to lock down:
  - is_enabled() requires both client_id and client_secret
  - build_authorize_url emits required PKCE / state / scope params
  - exchange_code raises OAuthExchangeError on every transport / decode /
    validation failure path the route layer translates to "exchange_failed"
  - GitHub primary email verified flag drives `email_verified`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from stock_trading_system.auth.oauth_providers import (
    OAuthExchangeError,
    get_enabled_providers,
)
from stock_trading_system.auth.oauth_providers.github import GitHubProvider
from stock_trading_system.auth.oauth_providers.google import GoogleProvider


# ── get_enabled_providers ─────────────────────────────────────────────────────


def test_get_enabled_providers_skips_when_no_env(monkeypatch):
    for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
              "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert get_enabled_providers({}) == {}


def test_get_enabled_providers_filters_partial_config(monkeypatch):
    """client_id without client_secret → provider must NOT register."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "gid")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    assert get_enabled_providers({}) == {}


def test_get_enabled_providers_returns_both(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "gsec")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "ghid")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "ghsec")
    out = get_enabled_providers({})
    assert set(out.keys()) == {"google", "github"}


# ── Google authorize URL ─────────────────────────────────────────────────────


def test_google_authorize_url_has_pkce_and_required_params(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "GID")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "GSEC")
    g = GoogleProvider({})
    url = g.build_authorize_url(
        state="STATE", code_challenge="CHALLENGE",
        redirect_uri="https://example.com/cb",
    )
    for fragment in (
        "client_id=GID",
        "state=STATE",
        "code_challenge=CHALLENGE",
        "code_challenge_method=S256",
        "response_type=code",
        "scope=openid+email+profile",
        "access_type=offline",
        "prompt=consent",
    ):
        assert fragment in url, f"missing {fragment!r} in {url!r}"


# ── Google exchange — error paths ────────────────────────────────────────────


def _enable_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "GID")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "GSEC")


def test_google_exchange_wraps_network_failure(monkeypatch):
    _enable_google(monkeypatch)
    g = GoogleProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.google.requests.post",
        side_effect=_requests.Timeout("boom"),
    ):
        with pytest.raises(OAuthExchangeError) as exc:
            g.exchange_code(code="c", code_verifier="v",
                            redirect_uri="https://x.com/cb")
        assert "token exchange failed" in str(exc.value)


def test_google_exchange_rejects_missing_id_token(monkeypatch):
    _enable_google(monkeypatch)
    g = GoogleProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.google.requests.post"
    ) as mp:
        mp.return_value.raise_for_status = lambda: None
        mp.return_value.json = lambda: {"access_token": "AT"}
        with pytest.raises(OAuthExchangeError) as exc:
            g.exchange_code(code="c", code_verifier="v",
                            redirect_uri="https://x.com/cb")
        assert "missing id_token" in str(exc.value)


def test_google_exchange_invalid_id_token_raises(monkeypatch):
    _enable_google(monkeypatch)
    g = GoogleProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.google.requests.post"
    ) as mp, patch(
        "stock_trading_system.auth.oauth_providers.google.requests.get"
    ) as mg:
        mp.return_value.raise_for_status = lambda: None
        mp.return_value.json = lambda: {
            "access_token": "AT", "id_token": "bogus.token.value"
        }
        mg.return_value.raise_for_status = lambda: None
        mg.return_value.json = lambda: {"keys": []}
        with pytest.raises(OAuthExchangeError) as exc:
            g.exchange_code(code="c", code_verifier="v",
                            redirect_uri="https://x.com/cb")
        assert "id_token validation failed" in str(exc.value)


# ── GitHub exchange ──────────────────────────────────────────────────────────


def _enable_github(monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "GHID")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "GHSEC")


def test_github_exchange_happy_path_verified_email(monkeypatch):
    _enable_github(monkeypatch)
    gh = GitHubProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.github.requests.post"
    ) as mp, patch(
        "stock_trading_system.auth.oauth_providers.github.requests.get"
    ) as mg:
        mp.return_value.raise_for_status = lambda: None
        mp.return_value.json = lambda: {"access_token": "AT"}
        user_resp = MagicMock()
        user_resp.raise_for_status = lambda: None
        user_resp.json = lambda: {"id": 9876, "login": "octo", "name": "Octo"}
        emails_resp = MagicMock()
        emails_resp.raise_for_status = lambda: None
        emails_resp.json = lambda: [
            {"email": "octo@x.com", "primary": True, "verified": True}
        ]
        mg.side_effect = [user_resp, emails_resp]
        profile, tokens = gh.exchange_code(
            code="c", code_verifier="v", redirect_uri="https://x.com/cb",
        )
    assert profile.sub == "9876"
    assert profile.email == "octo@x.com"
    assert profile.email_verified is True
    assert tokens.access_token == "AT"


def test_github_exchange_unverified_primary_email(monkeypatch):
    _enable_github(monkeypatch)
    gh = GitHubProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.github.requests.post"
    ) as mp, patch(
        "stock_trading_system.auth.oauth_providers.github.requests.get"
    ) as mg:
        mp.return_value.raise_for_status = lambda: None
        mp.return_value.json = lambda: {"access_token": "AT"}
        user_resp = MagicMock()
        user_resp.raise_for_status = lambda: None
        user_resp.json = lambda: {"id": 1, "login": "a"}
        emails_resp = MagicMock()
        emails_resp.raise_for_status = lambda: None
        emails_resp.json = lambda: [
            {"email": "a@x.com", "primary": True, "verified": False},
        ]
        mg.side_effect = [user_resp, emails_resp]
        profile, _ = gh.exchange_code(
            code="c", code_verifier="v", redirect_uri="https://x.com/cb",
        )
    # Provider did NOT verify — auto-merge gate must reject this downstream.
    assert profile.email_verified is False


def test_github_exchange_token_endpoint_error(monkeypatch):
    _enable_github(monkeypatch)
    gh = GitHubProvider({})
    with patch(
        "stock_trading_system.auth.oauth_providers.github.requests.post"
    ) as mp:
        mp.return_value.raise_for_status = lambda: None
        mp.return_value.json = lambda: {"error": "bad_verification_code"}
        with pytest.raises(OAuthExchangeError) as exc:
            gh.exchange_code(code="c", code_verifier="v",
                             redirect_uri="https://x.com/cb")
        assert "bad_verification_code" in str(exc.value)
