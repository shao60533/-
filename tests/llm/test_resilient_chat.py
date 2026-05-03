"""llm-fallback v1.0 — :func:`build_resilient_chat` contract.

Pins:
* secondary missing key → bare primary (no wrapper, no regression)
* fallback explicitly disabled → bare primary
* rate-limit on primary → secondary invoked; counter bumps
* non-rate-limit error on primary → propagates; counter stays 0
* ``with_structured_output`` is exposed on the wrapped runnable
* reverse direction (qwen primary → gemini secondary) works too
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.llm.resilient_chat import (
    build_resilient_chat,
    get_fallback_counters,
    reset_fallback_counters,
)


@pytest.fixture(autouse=True)
def _reset_counters_each_test():
    reset_fallback_counters()
    yield
    reset_fallback_counters()


def _config(qwen_key: str = "sk-q", gemini_key: str = "AIza-g",
            fallback: bool = True, primary: str = "gemini") -> dict:
    """Minimal config that mirrors what ``get_active_provider`` reads.

    ``llm_provider`` (legacy active flag) drives the primary; tests can
    flip it to test both directions.
    """
    return {
        "llm_provider": primary,
        "qwen": {"api_key": qwen_key, "model": "qwen-plus"},
        "gemini": {"api_key": gemini_key, "model": "gemini-2.5-flash"},
        "llm": {"fallback_enabled": fallback},
    }


def test_returns_bare_primary_when_secondary_lacks_key():
    """Single-provider deployments must not eat an extra _build_chat
    call (and the returned object should be the primary chat verbatim
    so legacy isinstance checks keep working)."""
    cfg = _config(qwen_key="")  # only gemini configured
    fake = MagicMock()
    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        return_value=fake,
    ) as m:
        chat = build_resilient_chat(cfg, kind="quick")
        assert m.call_count == 1
        assert chat is fake


def test_returns_bare_primary_when_disabled():
    """Operators can disable fallback via ``llm.fallback_enabled``;
    behavior must match pre-v1.0 exactly (no wrapper)."""
    cfg = _config(fallback=False)
    fake = MagicMock()
    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        return_value=fake,
    ) as m:
        chat = build_resilient_chat(cfg, kind="quick")
        assert m.call_count == 1
        assert chat is fake


def test_falls_back_on_rate_limit():
    cfg = _config()
    fake_primary = MagicMock()
    # RuntimeError("HTTP 429 ...") routes through the string-match
    # path of is_rate_limit_error so we don't need to import provider
    # SDK error types here.
    fake_primary.invoke.side_effect = RuntimeError("HTTP 429 quota")
    fake_secondary = MagicMock()
    fake_secondary.invoke.return_value = "secondary_response"

    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        side_effect=[fake_primary, fake_secondary],
    ):
        chat = build_resilient_chat(cfg, kind="quick")
        result = chat.invoke("test_input")

    assert result == "secondary_response"
    assert get_fallback_counters()["gemini→qwen"] == 1


def test_does_not_fall_back_on_non_rate_limit_error():
    """Auth errors must propagate so the user sees the real bug
    instead of getting a silent secondary attempt."""
    cfg = _config()
    fake_primary = MagicMock()
    fake_primary.invoke.side_effect = ValueError("invalid api key")
    fake_secondary = MagicMock()

    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        side_effect=[fake_primary, fake_secondary],
    ):
        chat = build_resilient_chat(cfg, kind="quick")
        with pytest.raises(ValueError, match="invalid api key"):
            chat.invoke("test_input")

    assert get_fallback_counters()["gemini→qwen"] == 0
    fake_secondary.invoke.assert_not_called()


def test_with_structured_output_works_through_fallback():
    """``RenderingExtractor`` calls ``chat.with_structured_output(Schema)``
    — the wrapper must inherit it from RunnableWithFallbacks."""
    cfg = _config()
    fake_primary = MagicMock()
    fake_secondary = MagicMock()
    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        side_effect=[fake_primary, fake_secondary],
    ):
        chat = build_resilient_chat(cfg, kind="quick")
        assert hasattr(chat, "with_structured_output")


def test_qwen_primary_falls_back_to_gemini():
    """Reverse direction — counter dimension is keyed
    ``{primary}→{secondary}`` so ops can tell which side ran out."""
    cfg = _config(primary="qwen")
    fake_primary = MagicMock()
    fake_primary.invoke.side_effect = RuntimeError("rate limit reached")
    fake_secondary = MagicMock()
    fake_secondary.invoke.return_value = "gemini_response"

    with patch(
        "stock_trading_system.llm.resilient_chat._build_chat",
        side_effect=[fake_primary, fake_secondary],
    ):
        chat = build_resilient_chat(cfg, kind="quick")
        result = chat.invoke("test_input")

    assert result == "gemini_response"
    assert get_fallback_counters()["qwen→gemini"] == 1
