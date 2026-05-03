"""Detect rate-limit / quota-exhaustion errors across providers.

google-api-core (Gemini) and the openai SDK (Qwen via OpenAI-compat
endpoint) raise different types for the underlying 429 status. The
LangChain wrappers occasionally re-wrap them too. This module
normalises all variants behind a single ``is_rate_limit_error(exc)``
predicate so :mod:`stock_trading_system.llm.resilient_chat` can do
provider fallback only on rate-limit signals — auth, validation, and
network errors must propagate so they don't get masked.

Order of checks (cheapest first):
    1. Concrete exception classes from each SDK (when importable).
    2. ``httpx.HTTPStatusError`` with ``response.status_code == 429``.
    3. String-match fallback for wrapped / translated messages.

Strings checked deliberately exclude generic words like ``"rate"`` or
``"limit"`` alone — those would false-positive on phrases like
"market rate limits" found in LLM reasoning that happens to surface
inside an exception message.
"""

from __future__ import annotations


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return True iff the exception is a rate-limit / quota / 429 error.

    Order: type-based first (cheap), then string-match fallback for
    subclassed wrappers like ``httpx.HTTPStatusError`` or LangChain-
    wrapped provider errors.
    """
    # google-api-core (legacy Gemini SDK path)
    try:
        from google.api_core.exceptions import (
            ResourceExhausted, TooManyRequests,
        )
        if isinstance(exc, (ResourceExhausted, TooManyRequests)):
            return True
    except ImportError:
        pass

    # google-genai (new SDK used by langchain-google-genai 4.x). Raises
    # ``ClientError`` with ``code=429`` for quota / rate-limit responses.
    try:
        from google.genai.errors import APIError
        if isinstance(exc, APIError) and getattr(exc, "code", None) == 429:
            return True
    except ImportError:
        pass

    # openai SDK (Qwen via OpenAI-compat API + any other openai-shaped
    # gateway). RateLimitError is a subclass of APIStatusError, but the
    # explicit check is cheaper and survives older SDK versions.
    try:
        from openai import RateLimitError
        if isinstance(exc, RateLimitError):
            return True
    except ImportError:
        pass
    try:
        from openai import APIStatusError
        if isinstance(exc, APIStatusError) and getattr(
            exc, "status_code", None,
        ) == 429:
            return True
    except ImportError:
        pass

    # httpx (used internally by both SDKs and by some LangChain shims)
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 429:
                return True
    except ImportError:
        pass

    # String fallback (covers wrapped/translated errors, e.g. when the
    # LangChain wrapper re-raises as a plain RuntimeError or the SDK
    # has wrapped a 429 inside a generic exception during streaming).
    msg = str(exc).lower()
    return any(token in msg for token in (
        "429",
        "rate limit",
        "rate_limit",
        "quota",
        "resource_exhausted",
        "resource has been exhausted",
        "too many requests",
    ))
