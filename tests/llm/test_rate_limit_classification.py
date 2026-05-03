"""llm-fallback v1.0 — ``is_rate_limit_error`` predicate contract.

Pins the predicate behaviour so a future SDK upgrade can't silently
break cross-provider fallback. Each provider's native 429 type plus
the LangChain/httpx wrappers must classify; auth / 5xx / validation
errors must NOT classify (otherwise we'd mask real bugs).
"""

from __future__ import annotations

import pytest

from stock_trading_system.llm.rate_limit import is_rate_limit_error


def test_classifies_google_resource_exhausted():
    """Either the legacy ``google.api_core.ResourceExhausted`` or the
    new ``google.genai.errors.ClientError(code=429)`` must classify —
    both ship with current Gemini SDK families."""
    classified = False
    try:
        from google.api_core.exceptions import ResourceExhausted  # type: ignore
        assert is_rate_limit_error(ResourceExhausted("Quota exceeded"))
        classified = True
    except ImportError:
        pass
    try:
        from google.genai.errors import ClientError  # type: ignore
        err = ClientError(code=429, response_json={"error": "quota"})
        assert is_rate_limit_error(err)
        classified = True
    except ImportError:
        pass
    if not classified:
        pytest.skip("neither google.api_core nor google.genai available")


def test_classifies_openai_rate_limit_error():
    pytest.importorskip("openai")
    pytest.importorskip("httpx")
    import httpx
    from openai import RateLimitError
    # The openai SDK requires a real httpx.Response so it can read
    # ``.request`` in __init__. Build the minimum that satisfies it.
    req = httpx.Request("POST", "https://example.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    try:
        err = RateLimitError("Rate limit reached", response=resp, body=None)
    except TypeError:
        # Older openai-python (pre-1.0) accepted only the message.
        err = RateLimitError("Rate limit reached")
    assert is_rate_limit_error(err)


def test_classifies_httpx_429():
    pytest.importorskip("httpx")
    import httpx
    req = httpx.Request("POST", "https://example.com")
    resp = httpx.Response(429, request=req)
    err = httpx.HTTPStatusError("rate limited", request=req, response=resp)
    assert is_rate_limit_error(err)


def test_string_fallback_429():
    assert is_rate_limit_error(RuntimeError("HTTP 429: too many requests"))


def test_string_fallback_quota():
    assert is_rate_limit_error(ValueError("Quota exhausted for project xyz"))


def test_string_fallback_rate_limit():
    assert is_rate_limit_error(Exception("API rate_limit reached"))


def test_string_fallback_resource_exhausted():
    assert is_rate_limit_error(Exception("resource_exhausted"))


def test_does_not_match_500():
    """5xx is a real backend bug — must surface, must not trigger
    fallback (the secondary likely sees the same problem)."""
    assert not is_rate_limit_error(RuntimeError("HTTP 500: internal server error"))


def test_does_not_match_auth_error():
    """An auth misconfig must visibly fail rather than silently fall
    back — the user has to fix the key, fallback can't help."""
    assert not is_rate_limit_error(ValueError("API key invalid"))


def test_does_not_match_validation_error():
    """Validation errors come from our own schema; the secondary
    provider would produce the same shape, no point falling back."""
    assert not is_rate_limit_error(ValueError("schema validation failed"))
