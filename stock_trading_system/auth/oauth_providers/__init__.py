"""OAuth provider abstraction for quick sign-in (Google + GitHub, v1.0).

Each provider plugs into the same Protocol so the route layer never needs
to switch on `provider_name` past the dispatch table. Adding a third
provider is purely a matter of:

  1. implementing the Protocol in a new module under this package, and
  2. wiring its env detection into `get_enabled_providers()`.

The shared dataclasses (`OAuthProfile`, `OAuthTokens`) carry the minimal
information the rest of the stack persists into oauth_accounts. Anything
provider-specific is preserved verbatim in `OAuthProfile.raw` for audit
purposes — the column is JSON-encoded, never read back as authoritative
state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class OAuthProfile:
    """Normalized user profile returned by a provider after token exchange."""
    sub: str
    email: Optional[str]
    email_verified: bool
    name: Optional[str]
    raw: dict


@dataclass(frozen=True)
class OAuthTokens:
    """Tokens returned by a provider's token endpoint."""
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[str]


class OAuthExchangeError(Exception):
    """Raised when token exchange or profile fetch fails for any reason.

    Wraps every transport, decode, and validation failure under one
    exception so the route layer can translate the whole class to a
    single user-facing 'exchange_failed' redirect without case analysis.
    """


class OAuthProvider(Protocol):
    """Interface every provider implementation must satisfy."""

    name: str
    label: str

    def is_enabled(self) -> bool: ...

    def build_authorize_url(
        self,
        *,
        state: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str: ...

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> tuple[OAuthProfile, OAuthTokens]: ...


def get_enabled_providers(config: dict) -> dict[str, OAuthProvider]:
    """Return the set of providers that are configured at startup.

    Detection is env-only: presence of `<PROVIDER>_OAUTH_CLIENT_ID` is
    sufficient to register the provider. The `is_enabled()` per-provider
    check additionally requires the matching client_secret — a deployment
    that sets only the client_id (typo / partial config) gets a clear
    "exchange_failed" surface rather than a silently-disabled button.
    """
    from stock_trading_system.auth.oauth_providers.google import GoogleProvider
    from stock_trading_system.auth.oauth_providers.github import GitHubProvider

    out: dict[str, OAuthProvider] = {}
    if os.environ.get("GOOGLE_OAUTH_CLIENT_ID"):
        google = GoogleProvider(config)
        if google.is_enabled():
            out["google"] = google
    if os.environ.get("GITHUB_OAUTH_CLIENT_ID"):
        github = GitHubProvider(config)
        if github.is_enabled():
            out["github"] = github
    return out


__all__ = [
    "OAuthProfile",
    "OAuthTokens",
    "OAuthProvider",
    "OAuthExchangeError",
    "get_enabled_providers",
]
