"""Fernet-based encryption for OAuth tokens at rest (oauth_accounts table).

The Fernet key is sourced from the OAUTH_ENCRYPT_KEY env var. It is generated
once via:

    python -c "from cryptography.fernet import Fernet; \\
               print(Fernet.generate_key().decode())"

and persisted out-of-band (cloud KMS, persistent volume, secret manager).
Losing the key makes historical tokens unreadable; v1.0 does not consume the
encrypted access_token at runtime so loss is recoverable by re-binding, but
it forfeits the audit trail.

`assert_key_configured()` is invoked at app startup to fail-fast — refusing
to write tokens without a key is a far better failure mode than silently
storing them in plaintext.
"""

from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class OAuthKeyError(RuntimeError):
    """Raised when OAUTH_ENCRYPT_KEY is missing or malformed."""


def _key() -> bytes:
    raw = os.environ.get("OAUTH_ENCRYPT_KEY", "").strip()
    if not raw:
        raise OAuthKeyError(
            "OAUTH_ENCRYPT_KEY env not set — generate via "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'`"
        )
    return raw.encode()


def encrypt_token(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a token. Returns None when input is None/empty."""
    if not plaintext:
        return None
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a previously encrypted token. Returns None on empty input.

    Raises cryptography.fernet.InvalidToken if the ciphertext is corrupt
    or was encrypted with a different key — caller should let it surface
    rather than silently treating it as a missing token.
    """
    if not ciphertext:
        return None
    return Fernet(_key()).decrypt(ciphertext.encode()).decode()


def assert_key_configured() -> None:
    """Verify OAUTH_ENCRYPT_KEY is set and Fernet-shaped at app startup.

    Raises OAuthKeyError when missing; raises ValueError (from Fernet) on
    malformed key (wrong length / not base64). Either is fatal — the app
    must not boot in a state where it would persist plaintext tokens.
    """
    Fernet(_key())  # Constructor validates key shape.


__all__ = [
    "OAuthKeyError",
    "InvalidToken",
    "assert_key_configured",
    "encrypt_token",
    "decrypt_token",
]
