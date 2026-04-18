"""TC-MS-U1 ~ U12: Provider resolver unit tests."""

from __future__ import annotations

import pytest

from stock_trading_system.llm.router import (
    get_active_provider,
    has_provider_key,
    is_provider_locked_by_env,
)


# ── TC-MS-U1: env beats config ────────────────────────────────────


@pytest.mark.unit
def test_env_beats_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    cfg = {"llm_provider": "qwen", "qwen": {"api_key": "k"}, "gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"


# ── TC-MS-U2: config beats legacy ─────────────────────────────────


def test_config_beats_legacy(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"llm_provider": "gemini", "qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "gemini"


# ── TC-MS-U3: legacy — has qwen key → qwen ────────────────────────


def test_legacy_qwen(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"


# ── TC-MS-U4: legacy — no qwen key → gemini ───────────────────────


def test_legacy_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"


# ── TC-MS-U5: config null → no warning, legacy fallback ───────────


def test_config_null_no_warning(monkeypatch, caplog):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"llm_provider": None, "qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"
    assert "Ignoring unknown" not in caplog.text


# ── TC-MS-U6: env case insensitive ────────────────────────────────


@pytest.mark.parametrize("val", ["QWEN", "Qwen", "qwen", "  qwen  "])
def test_env_case_insensitive(monkeypatch, val):
    monkeypatch.setenv("LLM_PROVIDER", val)
    assert get_active_provider({}) == "qwen"


# ── TC-MS-U7: env unknown → fallback + warning ────────────────────


def test_env_unknown_fallback(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    cfg = {"qwen": {"api_key": "k"}}
    assert get_active_provider(cfg) == "qwen"
    assert "Ignoring unknown LLM_PROVIDER" in caplog.text


# ── TC-MS-U8: config unknown → fallback + warning ─────────────────


def test_config_unknown_fallback(monkeypatch, caplog):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"llm_provider": "deepseek", "gemini": {"api_key": "g"}}
    assert get_active_provider(cfg) == "gemini"
    assert "Ignoring unknown config.llm_provider" in caplog.text


# ── TC-MS-U9: is_provider_locked_by_env — not set → False ─────────


def test_lock_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert is_provider_locked_by_env() is False


# ── TC-MS-U10: is_provider_locked_by_env — valid → True ───────────


def test_lock_valid(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    assert is_provider_locked_by_env() is True


# ── TC-MS-U11: is_provider_locked_by_env — empty string → False ───


def test_lock_empty(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    assert is_provider_locked_by_env() is False


# ── TC-MS-U12: has_provider_key ───────────────────────────────────


def test_has_qwen_key_true():
    assert has_provider_key({"qwen": {"api_key": "sk-abc"}}, "qwen") is True


def test_has_qwen_key_false():
    assert has_provider_key({"qwen": {"api_key": ""}}, "qwen") is False


def test_has_gemini_key_true():
    assert has_provider_key({"gemini": {"api_key": "AIza"}}, "gemini") is True


def test_has_gemini_key_false():
    assert has_provider_key({}, "gemini") is False
