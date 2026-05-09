"""GitHub OAuth provider.

GitHub does not implement OIDC, so:

* There is no id_token to validate.
* `email_verified` is determined by hitting `/user/emails` and reading the
  primary verified flag. v1.0 refuses auto-merge unless `verified=true`,
  to keep the same security posture as Google.
* PKCE is not supported by GitHub's authorization server. The OAuth flow
  still passes a code_challenge through `build_authorize_url` for parity
  with the protocol but GitHub ignores it; the verifier on the callback
  side is therefore not consumed by `exchange_code`.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import requests

from stock_trading_system.auth.oauth_providers import (
    OAuthExchangeError,
    OAuthProfile,
    OAuthTokens,
)
from stock_trading_system.utils import get_logger

logger = get_logger("auth.oauth_providers.github")


_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"
_REQUEST_TIMEOUT_SEC = 10
_USER_AGENT = "StockAI-Terminal"


class GitHubProvider:
    name = "github"
    label = "用 GitHub 登录"

    def __init__(self, config: dict) -> None:
        self._client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip()
        self._client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip()

    def is_enabled(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def build_authorize_url(
        self,
        *,
        state: str,
        code_challenge: str,  # noqa: ARG002 — GitHub ignores PKCE; kept for Protocol parity
        redirect_uri: str,
    ) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,  # noqa: ARG002 — GitHub does not accept PKCE verifier
        redirect_uri: str,
    ) -> tuple[OAuthProfile, OAuthTokens]:
        # 1. Exchange authorization code for an access_token.
        try:
            resp = requests.post(
                _TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=_REQUEST_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise OAuthExchangeError(f"github token exchange failed: {exc}") from exc

        access_token = payload.get("access_token")
        if not access_token:
            error = payload.get("error") or "missing access_token"
            raise OAuthExchangeError(f"github token response error: {error}")

        # 2. Fetch user + emails; primary verified email decides auto-merge.
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            user_resp = requests.get(_USER_URL, headers=headers,
                                     timeout=_REQUEST_TIMEOUT_SEC)
            user_resp.raise_for_status()
            user = user_resp.json()
            emails_resp = requests.get(_EMAILS_URL, headers=headers,
                                       timeout=_REQUEST_TIMEOUT_SEC)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise OAuthExchangeError(f"github profile fetch failed: {exc}") from exc

        if not isinstance(user, dict) or "id" not in user:
            raise OAuthExchangeError("github user response missing id")
        if not isinstance(emails, list):
            raise OAuthExchangeError("github emails response not a list")

        primary_email = None
        primary_verified = False
        for entry in emails:
            if isinstance(entry, dict) and entry.get("primary"):
                primary_email = entry.get("email")
                primary_verified = bool(entry.get("verified", False))
                break

        profile = OAuthProfile(
            sub=str(user["id"]),
            email=primary_email,
            email_verified=primary_verified,
            name=user.get("name") or user.get("login"),
            raw={"user": user, "emails": emails},
        )

        tokens = OAuthTokens(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_at=None,
        )

        logger.info(
            "github oauth exchange ok sub=%s email_verified=%s",
            profile.sub, profile.email_verified,
        )
        return profile, tokens
