"""Tests for OAuth Fernet encryption layer.

Goal: prove the fail-fast behavior of `assert_key_configured` and the
round-trip correctness / nullable handling of `encrypt_token` /
`decrypt_token`. Each test sets/unsets `OAUTH_ENCRYPT_KEY` via monkeypatch
so leaks across tests are impossible.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from stock_trading_system.auth.oauth_crypto import (
    OAuthKeyError,
    assert_key_configured,
    decrypt_token,
    encrypt_token,
)


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("OAUTH_ENCRYPT_KEY", key)
    return key


def test_assert_key_configured_raises_when_missing(monkeypatch):
    monkeypatch.delenv("OAUTH_ENCRYPT_KEY", raising=False)
    with pytest.raises(OAuthKeyError):
        assert_key_configured()


def test_assert_key_configured_raises_on_malformed_key(monkeypatch):
    monkeypatch.setenv("OAUTH_ENCRYPT_KEY", "not-a-valid-fernet-key")
    # cryptography raises ValueError; OAuthKeyError covers the env-missing
    # case. Either is fatal — the boot must refuse to write tokens.
    with pytest.raises((ValueError, OAuthKeyError)):
        assert_key_configured()


def test_round_trip_and_null_passthrough(fernet_key):
    ct = encrypt_token("at_secret_value")
    assert ct is not None
    assert "at_secret_value" not in ct  # must not leak plaintext
    assert decrypt_token(ct) == "at_secret_value"

    # None / empty input passes through both directions.
    assert encrypt_token(None) is None
    assert encrypt_token("") is None
    assert decrypt_token(None) is None
    assert decrypt_token("") is None

    # Tampered ciphertext raises rather than silently returning garbage —
    # the route layer must surface this as a hard failure. We flip a
    # middle byte to defeat Fernet's HMAC; a trailing append can sometimes
    # decode as a longer-but-still-valid token.
    corrupt = ct[:30] + ("Z" if ct[30] != "Z" else "Y") + ct[31:]
    with pytest.raises(InvalidToken):
        decrypt_token(corrupt)
