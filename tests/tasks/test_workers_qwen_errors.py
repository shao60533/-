"""Friendly error-message wrapping for analysis worker failures.

Verifies ``wrap_llm_error`` maps the common LLM provider failure shapes
(missing key, 401/403, model-not-found, timeout, rate-limit) to human
readable Chinese strings, and that the analysis worker re-raises with
the wrapped message while preserving the original traceback via
``__cause__`` so ``error_trace`` still captures full debug context.
"""

from __future__ import annotations

import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_trading_system.tasks.workers import (
    make_analysis_worker, wrap_llm_error,
)


# ── Pure unit tests on wrap_llm_error ────────────────────────────────────────


def test_wrap_qwen_missing_key():
    msg = wrap_llm_error(KeyError("QWEN_API_KEY"))
    assert msg == "Qwen API Key 未配置"


def test_wrap_dashscope_missing_key():
    msg = wrap_llm_error(KeyError("DASHSCOPE_API_KEY"))
    assert msg == "Qwen API Key 未配置"


def test_wrap_gemini_missing_key():
    msg = wrap_llm_error(KeyError("GEMINI_API_KEY"))
    assert msg == "Gemini API Key 未配置"


def test_wrap_unknown_env_key():
    msg = wrap_llm_error(KeyError("MYSTERY_KEY"))
    assert msg == "环境变量 MYSTERY_KEY 未配置"


def test_wrap_qwen_401():
    msg = wrap_llm_error(
        RuntimeError("HTTP 401: invalid API key"),
        provider="qwen", model="qwen-plus",
    )
    assert msg == "Qwen 认证失败，请检查 API Key"


def test_wrap_gemini_403():
    msg = wrap_llm_error(
        RuntimeError("HTTP 403 forbidden"),
        provider="gemini", model="gemini-2.5-flash",
    )
    assert msg == "Gemini 认证失败，请检查 API Key"


def test_wrap_invalid_api_key_phrase():
    msg = wrap_llm_error(
        RuntimeError("Error: invalid_api_key from upstream"),
        provider="qwen", model="qwen-plus",
    )
    assert "认证失败" in msg


def test_wrap_model_not_found():
    msg = wrap_llm_error(
        RuntimeError("HTTP 404: model_not_found"),
        provider="qwen", model="qwen-bogus",
    )
    assert msg == "Qwen 模型不可用：qwen-bogus"


def test_wrap_timeout_error():
    msg = wrap_llm_error(TimeoutError("request timed out"))
    assert "超时" in msg


def test_wrap_timeout_message():
    msg = wrap_llm_error(RuntimeError("Connection timeout after 60s"))
    assert "超时" in msg


def test_wrap_rate_limit():
    msg = wrap_llm_error(
        RuntimeError("HTTP 429 too many requests"),
        provider="qwen", model="qwen-plus",
    )
    assert "限流" in msg


def test_wrap_unknown_passes_through():
    msg = wrap_llm_error(RuntimeError("some weird thing happened"))
    assert msg == "some weird thing happened"


def test_wrap_empty_message_falls_back_to_class_name():
    msg = wrap_llm_error(RuntimeError())
    assert msg == "RuntimeError"


# ── Integration: analysis worker re-raises with friendly message ─────────────


class _FakeStrategyEngine:
    def generate_advice(self, result, holdings, current_price):
        return None


class _FakePortfolio:
    def get_holdings(self):
        return []


class _FakeRouter:
    def __init__(self):
        self.get_price = MagicMock(return_value={"last": 150})


class _BombAnalyzer:
    """Analyzer that raises a configured exception when called."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def analyze(self, ticker, date, progress_cb=None, depth=None):
        raise self._exc


def _make_worker(exc):
    return make_analysis_worker(
        get_analyzer=lambda: _BombAnalyzer(exc),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakePortfolio(),
        get_router=lambda: _FakeRouter(),
    )


def test_worker_wraps_qwen_missing_key_into_runtime_error():
    worker = _make_worker(KeyError("QWEN_API_KEY"))
    with pytest.raises(RuntimeError, match="Qwen API Key 未配置"):
        worker({"ticker": "AAPL", "date": "2026-04-15"},
               lambda *a, **k: None)


def test_worker_wraps_401_into_friendly_runtime_error():
    worker = _make_worker(RuntimeError("HTTP 401: invalid api key"))
    with pytest.raises(RuntimeError, match="认证失败"):
        worker({"ticker": "AAPL", "date": "2026-04-15"},
               lambda *a, **k: None)


def test_worker_wraps_timeout_into_friendly_runtime_error():
    worker = _make_worker(TimeoutError("request timed out"))
    with pytest.raises(RuntimeError, match="超时"):
        worker({"ticker": "AAPL", "date": "2026-04-15"},
               lambda *a, **k: None)


def test_worker_preserves_original_exception_in_cause_chain():
    """error_trace = traceback.format_exc(); the chain must still expose
    the original exception class and message so operators can debug."""
    original = RuntimeError("DashScope 401 Unauthorized: token sk-***-revoked")
    worker = _make_worker(original)
    try:
        worker({"ticker": "AAPL", "date": "2026-04-15"},
               lambda *a, **k: None)
    except RuntimeError as wrapped:
        # Friendly message on the new RuntimeError
        assert "认证失败" in str(wrapped)
        # __cause__ chains back to the original exception verbatim
        assert wrapped.__cause__ is original
        # And format_exc captures both — this is what task_manager._fail
        # writes into tasks.error_trace.
        trace = "".join(traceback.format_exception(
            type(wrapped), wrapped, wrapped.__traceback__,
        ))
        assert "DashScope 401" in trace
        assert "RuntimeError" in trace
    else:  # pragma: no cover — defensive
        pytest.fail("worker should have raised")


def test_worker_passes_value_error_unchanged():
    """Validation errors keep their own message — they're already user-readable."""
    worker = make_analysis_worker(
        get_analyzer=lambda: _BombAnalyzer(RuntimeError("unused")),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakePortfolio(),
        get_router=lambda: _FakeRouter(),
    )
    with pytest.raises(ValueError, match="ticker"):
        worker({"ticker": ""}, lambda *a, **k: None)
