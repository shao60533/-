"""OAuth session helpers: PKCE pair generation, safe-next URL guard,
and signed pending-token serialization for the brand-new-email register
hand-off.

Reasons each helper exists separately:

* `generate_pkce_pair()` — caller writes the verifier into Flask session
  during /start, sends the challenge to the provider, then reads the
  verifier back during /callback. Decoupled so unit tests don't need
  a live Flask request context.
* `safe_next()` — guards open-redirect: only same-origin relative paths
  survive. Callable independently of the request lifecycle.
* `make_pending_token` / `verify_pending_token` — single-use signed
  envelope handed to the front-end across the brand-new-email register
  detour. itsdangerous signs but does NOT encrypt; the access_token
  payload is short-lived (10-min TTL) and never leaves the user's own
  browser. Encryption at rest happens once oauth_accounts.upsert lands.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Optional
from urllib.parse import urlparse

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


PENDING_TOKEN_SALT = "oauth-pending-v1"
PENDING_TOKEN_MAX_AGE_SEC = 600  # 10 min


def generate_pkce_pair() -> tuple[str, str]:
    """Generate (verifier, challenge) for the S256 PKCE method.

    The verifier is 64 url-safe bytes. The challenge is the base64-url
    SHA-256 of the verifier with trailing '=' stripped, per RFC 7636.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def safe_next(url: Optional[str], default: str = "/") -> str:
    """Return a sanitized post-login redirect target.

    Only same-origin *relative* paths are allowed. Anything else
    (absolute URL, scheme-relative, missing leading slash) collapses
    to the default. Prevents login-success-redirect open-redirect.
    """
    if not url:
        return default
    parsed = urlparse(url)
    # Reject absolute URLs, scheme-relative, and protocol-relative.
    if parsed.scheme or parsed.netloc:
        return default
    if not url.startswith("/"):
        return default
    # Reject "//evil.com/path" (parsed as path-only by urlparse).
    if url.startswith("//"):
        return default
    return url


def make_pending_token(secret_key: str, payload: dict) -> str:
    """Serialize + sign a pending-OAuth-register payload."""
    serializer = URLSafeTimedSerializer(secret_key, salt=PENDING_TOKEN_SALT)
    return serializer.dumps(payload)


def verify_pending_token(
    secret_key: str,
    token: str,
    max_age: int = PENDING_TOKEN_MAX_AGE_SEC,
) -> Optional[dict]:
    """Verify and deserialize a pending token.

    Returns None when the token is missing, malformed, signature mismatched,
    or older than max_age seconds. Returning None (rather than raising) lets
    the route layer translate every failure mode to the same 400 response.
    """
    if not token:
        return None
    serializer = URLSafeTimedSerializer(secret_key, salt=PENDING_TOKEN_SALT)
    try:
        return serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
