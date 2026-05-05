"""StockAnalyzer OpenRouter provider integration.

docs/design/llm-openrouter.md v1.0 §6.4 — 3 cases:
    1. _configure_openrouter sets the right ta_config fields
    2. missing OR key raises (no silent fallback to default)
    3. graph cache key changes when active deep preset changes
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.agents.analyzer import StockAnalyzer


def _or_config(deep_id="deepseek-v4-pro", api_key="sk-or-test"):
    """Minimal yaml-shape config with OR enabled and 2 deep presets so
    cache-key tests can swap which one is active."""
    return {
        "openrouter": {
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
            "http_referer": "https://stockai.example.com",
            "x_title": "StockAI Terminal",
            "presets": [
                {"id": "deepseek-v4-pro", "label": "DS Pro",
                 "model": "deepseek/deepseek-v4-pro",
                 "role": "deep", "provider_order": ["deepseek", "novita"]},
                {"id": "gemini-3.1-pro", "label": "Gemini Pro",
                 "model": "google/gemini-3.1-pro-preview",
                 "role": "deep", "provider_order": ["google-ai-studio"]},
                {"id": "deepseek-v4-flash", "label": "DS Flash",
                 "model": "deepseek/deepseek-v4-flash",
                 "role": "quick", "provider_order": ["deepseek"]},
            ],
            "active": {"deep": deep_id, "quick": "deepseek-v4-flash"},
        },
        "qwen": {"api_key": ""},
        "gemini": {"api_key": ""},
        "iteration": {"enabled": False},
    }


@pytest.mark.integration
def test_configure_openrouter_sets_ta_config_fields(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    ta_config: dict = {}
    analyzer._configure_openrouter(ta_config)

    # Provider routed to OR; deep + quick both pulled from preset registry
    assert ta_config["llm_provider"] == "openrouter"
    assert ta_config["deep_think_llm"] == "deepseek/deepseek-v4-pro"
    assert ta_config["quick_think_llm"] == "deepseek/deepseek-v4-flash"
    assert ta_config["backend_url"] == "https://openrouter.ai/api/v1"
    # Timeout policy: deep gets 10min for long reasoning chains.
    assert ta_config["llm_deep_kwargs"]["timeout"] == 600
    assert ta_config["llm_quick_kwargs"]["timeout"] == 120
    # Headers propagated for OR analytics
    assert ta_config["llm_default_headers"]["HTTP-Referer"] == "https://stockai.example.com"
    assert ta_config["llm_default_headers"]["X-Title"] == "StockAI Terminal"
    # Upstream factory reads from env, not config — _configure must
    # have stuffed the key into env so the factory can pick it up.
    import os
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-test"


@pytest.mark.integration
def test_configure_openrouter_raises_when_no_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config(api_key="")  # empty yaml key, no env
    analyzer = StockAnalyzer(cfg)

    with pytest.raises(RuntimeError, match="api_key is empty"):
        analyzer._configure_openrouter({})


@pytest.mark.integration
def test_graph_cache_key_changes_on_deep_preset_swap(monkeypatch):
    """The cache key for OR is ``openrouter:<deep_id>:<quick_id>`` so
    swapping the active deep preset (UI / yaml) creates a fresh
    TradingAgents graph with the new model bindings instead of
    silently reusing the old one."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config(deep_id="deepseek-v4-pro")
    analyzer = StockAnalyzer(cfg)

    # First _init_graph — should cache under deepseek-pro key.
    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph") as mock_tag:
        mock_tag.return_value = MagicMock()
        analyzer._init_graph()

    cache_keys_before = list(analyzer._graphs.keys())
    assert cache_keys_before == ["openrouter:deepseek-v4-pro:deepseek-v4-flash"]

    # Now the user swaps active.deep to gemini-3.1-pro (e.g. via UI POST
    # to /api/settings/openrouter/active). Mutate the live config dict
    # the analyzer holds — this mirrors what _reset_config_dependent_singletons
    # does in production after a save.
    analyzer._config["openrouter"]["active"]["deep"] = "gemini-3.1-pro"

    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph") as mock_tag:
        mock_tag.return_value = MagicMock()
        analyzer._init_graph()

    # New entry, not a cache hit.
    cache_keys_after = list(analyzer._graphs.keys())
    assert "openrouter:gemini-3.1-pro:deepseek-v4-flash" in cache_keys_after
    assert len(cache_keys_after) == 2


@pytest.mark.integration
def test_build_quick_llm_openrouter_uses_quick_preset(monkeypatch):
    """_build_quick_llm under provider=openrouter must construct
    ChatOpenAI bound to the active *quick* preset (not deep), with
    OR base_url and provider_order forwarded."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    with patch("langchain_openai.ChatOpenAI") as mock_chat:
        mock_chat.return_value = MagicMock()
        analyzer._build_quick_llm()

    call_kwargs = mock_chat.call_args.kwargs
    assert call_kwargs["model"] == "deepseek/deepseek-v4-flash"
    assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["extra_body"]["provider"]["order"] == ["deepseek"]
    assert call_kwargs["extra_body"]["provider"]["allow_fallbacks"] is True
