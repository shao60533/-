"""Router three-state — openrouter resolution paths.

Covers the four invariants from docs/design/llm-openrouter.md v1.0 §2.6:
    1. env LLM_PROVIDER=openrouter wins regardless of yaml/keys
    2. legacy auto-detect: only OPENROUTER_API_KEY env → openrouter
    3. has_provider_key honors env over yaml
    4. resolve_active_model returns the active deep preset's model
"""

from __future__ import annotations

import os

import pytest

from stock_trading_system.llm import router


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Wipe LLM-related env vars so individual tests can set what they need."""
    for k in ("LLM_PROVIDER", "OPENROUTER_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _config_with_or_presets() -> dict:
    return {
        "openrouter": {
            "api_key": "",
            "presets": [
                {"id": "deep-pro",   "label": "Deep Pro",
                 "model": "deepseek/deepseek-v4-pro",   "role": "deep"},
                {"id": "quick-flash", "label": "Quick Flash",
                 "model": "deepseek/deepseek-v4-flash", "role": "quick"},
            ],
            "active": {"deep": "deep-pro", "quick": "quick-flash"},
        },
    }


def test_env_llm_provider_openrouter_wins(monkeypatch):
    """LLM_PROVIDER=openrouter overrides yaml + key auto-detect."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    cfg = {"qwen": {"api_key": "sk-qwen"}}  # qwen would otherwise win
    assert router.get_active_provider(cfg) == "openrouter"


def test_auto_detect_picks_openrouter_when_only_env_key_set(monkeypatch):
    """Cloud deploy: only OPENROUTER_API_KEY env, no yaml. Auto-detect
    must surface ``openrouter`` even with the qwen branch otherwise
    available — env-only activation is the v1.0 cloud contract."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = {}  # no yaml at all
    assert router.get_active_provider(cfg) == "openrouter"


def test_auto_detect_prefers_openrouter_over_qwen_key(monkeypatch):
    """When both qwen yaml key AND OPENROUTER_API_KEY env are present,
    auto-detect picks OR (cloud-first principle)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    cfg = {"qwen": {"api_key": "sk-qwen"}}
    assert router.get_active_provider(cfg) == "openrouter"


def test_has_provider_key_env_beats_yaml(monkeypatch):
    """has_provider_key('openrouter') accepts env-only or yaml-only."""
    cfg = {}
    # Env only
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    assert router.has_provider_key(cfg, "openrouter") is True
    # Yaml only
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = {"openrouter": {"api_key": "sk-or-yaml"}}
    assert router.has_provider_key(cfg, "openrouter") is True
    # Neither
    cfg = {"openrouter": {"api_key": ""}}
    assert router.has_provider_key(cfg, "openrouter") is False


def test_resolve_active_model_returns_deep_preset_model(monkeypatch):
    """When openrouter is active, resolve_active_model returns the
    *deep* preset's model id (not flash, not the literal preset id)."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    cfg = _config_with_or_presets()
    provider, model = router.resolve_active_model(cfg)
    assert provider == "openrouter"
    assert model == "deepseek/deepseek-v4-pro"
