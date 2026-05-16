"""Google OAuth 2.0 / OpenID Connect provider.

Google always sets `email_verified=true` on the OIDC id_token (per the
Google Identity Platform docs), so v1.0 trusts that claim for the auto-merge
path. The id_token is validated against Google's published JWKS, which
exposes signature + iss + aud + exp checks via authlib's `jwt.decode`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from stock_trading_system.utils.timez import now_local, now_utc
from typing import Any
from urllib.parse import urlencode

import requests
from authlib.jose import JsonWebKey, jwt

from stock_trading_system.auth.oauth_providers import (
    OAuthExchangeError,
    OAuthProfile,
    OAuthTokens,
)
from stock_trading_system.utils import get_logger

logger = get_logger("auth.oauth_providers.google")


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_REQUEST_TIMEOUT_SEC = 10


class GoogleProvider:
    name = "google"
    label = "用 Google 登录"

    def __init__(self, config: dict) -> None:
        # Config dict is currently unused but reserved for per-deployment
        # overrides (e.g. hosted-domain restriction `hd=`).
        self._client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        self._client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

    def is_enabled(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def build_authorize_url(
        self,
        *,
        state: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # access_type=offline + prompt=consent makes Google return a
            # refresh_token even on repeat sign-in. v1.0 doesn't consume
            # the refresh_token at runtime but persists it (encrypted) so
            # future scope expansions don't have to force a second consent.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> tuple[OAuthProfile, OAuthTokens]:
        # 1. Exchange authorization code for tokens (PKCE-protected).
        try:
            resp = requests.post(
                _TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=_REQUEST_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise OAuthExchangeError(f"google token exchange failed: {exc}") from exc

        id_token = payload.get("id_token")
        access_token = payload.get("access_token")
        if not id_token or not access_token:
            raise OAuthExchangeError(
                "google token response missing id_token/access_token"
            )

        # 2. Validate id_token signature against Google's JWKS.
        try:
            jwks_resp = requests.get(_JWKS_URL, timeout=_REQUEST_TIMEOUT_SEC)
            jwks_resp.raise_for_status()
            key_set = JsonWebKey.import_key_set(jwks_resp.json())
            claims = jwt.decode(id_token, key_set)
            claims.validate()  # exp / iat / nbf
        except Exception as exc:  # noqa: BLE001 — every JWKS/JWT failure → exchange_failed
            raise OAuthExchangeError(
                f"google id_token validation failed: {exc}"
            ) from exc

        sub = claims.get("sub")
        if not sub:
            raise OAuthExchangeError("google id_token missing sub claim")

        profile = OAuthProfile(
            sub=str(sub),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
            raw=dict(claims),
        )

        expires_at = None
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            # P2.5 step-2: OAuth tokens are time-compared against the
            # provider's UTC ``exp`` claim; store the absolute deadline
            # in UTC too so the comparator on read has matching tz.
            expires_at = (
                now_utc() + timedelta(seconds=int(expires_in))
            ).isoformat()

        tokens = OAuthTokens(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
        )

        logger.info("google oauth exchange ok sub=%s email_verified=%s",
                    profile.sub, profile.email_verified)
        return profile, tokens
