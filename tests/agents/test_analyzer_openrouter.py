"""StockAnalyzer OpenRouter provider integration.

docs/design/llm-openrouter.md v1.0 §6.4 — 3 cases:
    1. _configure_openrouter sets the right ta_config fields
    2. missing OR key raises (no silent fallback to default)
    3. graph cache key changes when active deep preset changes
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.agents.analyzer import StockAnalyzer


@pytest.fixture(autouse=True)
def _restore_or_env():
    """``_configure_openrouter`` writes ``os.environ['OPENROUTER_API_KEY']``
    directly so the upstream tradingagents factory can pick it up. That
    mutation isn't reverted by pytest's monkeypatch (which only tracks
    its own setenv calls), so without this fixture the OR tests leak the
    key into every subsequent test that reads env-driven provider state
    (notably tests/web/test_llm_provider_api.py::test_get_returns_state
    which expects active in {qwen, gemini}). Snapshot before / restore
    after so per-test setup is untouched but the leak is bounded.
    """
    snapshot = os.environ.get("OPENROUTER_API_KEY")
    yield
    if snapshot is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
    else:
        os.environ["OPENROUTER_API_KEY"] = snapshot


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
    # v1.0.1: cache key suffix is @<user_id|global> — no user_id passed
    # to analyze() in this test → @global.
    assert cache_keys_before == ["openrouter:deepseek-v4-pro:deepseek-v4-flash@global"]

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
    assert "openrouter:gemini-3.1-pro:deepseek-v4-flash@global" in cache_keys_after
    assert len(cache_keys_after) == 2


@pytest.mark.integration
def test_init_graph_uses_per_user_provider_and_cache_scope(monkeypatch):
    """v1.0.1 P1-B fix — analyzer.analyze(user_id=N) makes _init_graph
    resolve the provider with that user's scope (router honors
    user_settings.llm_provider) AND scopes the graph cache under the
    user id, so user A on qwen and user B on openrouter never share
    a graph.

    Verifies:
    - cache_key for user_id=42 + global LLM_PROVIDER=openrouter ends
      with '@42' rather than the legacy unscoped key.
    - cache_key for user_id=None still ends with '@global'.
    - Two different user ids produce two separate cache entries.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    # First init — user A
    analyzer._active_user_id = 42
    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph") as mock_tag:
        mock_tag.return_value = MagicMock()
        analyzer._init_graph()
    keys_a = list(analyzer._graphs.keys())
    assert any(k.endswith("@42") for k in keys_a), keys_a

    # Second init — user B
    analyzer._active_user_id = 99
    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph") as mock_tag:
        mock_tag.return_value = MagicMock()
        analyzer._init_graph()
    keys_b = list(analyzer._graphs.keys())
    assert any(k.endswith("@99") for k in keys_b), keys_b
    assert len(keys_b) == 2, "expected 2 cache entries for 2 different users"

    # Third init — no user_id (e.g. legacy direct caller). Maps to @global.
    analyzer._active_user_id = None
    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph") as mock_tag:
        mock_tag.return_value = MagicMock()
        analyzer._init_graph()
    keys_c = list(analyzer._graphs.keys())
    assert any(k.endswith("@global") for k in keys_c), keys_c
    assert len(keys_c) == 3


@pytest.mark.integration
def test_or_factory_patch_injects_provider_order_into_deep_call(monkeypatch):
    """v1.0.1 P1-A fix — the analyzer's _patch_tradingagents_qwen now
    also wraps create_llm_client so OpenRouter calls receive
    ``extra_body.provider.order`` + ``default_headers`` matching the
    active preset. Without this, the main 7-agent analysis path hit
    OR's primary endpoint without honoring the preset's vendor
    fallback chain.

    Verifies: when create_llm_client is invoked with provider=openrouter
    and model=<active deep model id>, the wrapper adds the deep
    preset's provider_order to extra_body and forwards Referer/Title
    headers from the OR config.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    # The patch reads config via get_config(), so swap the module-level
    # config getter to our test fixture. Reset _stockai_patched so
    # the patch reapplies under our config.
    from stock_trading_system.config import settings as cfg_settings
    from tradingagents.llm_clients import factory as _factory
    from tradingagents.llm_clients import openai_client as _oc

    or_cfg = _or_config()
    monkeypatch.setattr(cfg_settings, "get_config", lambda: or_cfg)
    # __init__ re-exports get_config so patch the bare module too —
    # production code does ``from stock_trading_system.config import get_config``.
    import stock_trading_system.config as _cfg_pkg
    monkeypatch.setattr(_cfg_pkg, "get_config", lambda: or_cfg)

    # Force re-patch by clearing the idempotency flag.
    if hasattr(_factory, "_stockai_patched"):
        monkeypatch.setattr(_factory, "_stockai_patched", False, raising=False)
    # Snapshot _PASSTHROUGH_KWARGS so we can verify it's extended; the
    # autouse env-restore fixture handles env.
    original_passthrough = tuple(_oc._PASSTHROUGH_KWARGS)
    monkeypatch.setattr(_oc, "_PASSTHROUGH_KWARGS", original_passthrough)
    original_factory = _factory.create_llm_client
    monkeypatch.setattr(_factory, "create_llm_client", original_factory)

    # Replace the unpatched factory itself with a capture stub. The
    # patched wrapper installed by ``_patch_tradingagents_qwen`` calls
    # the closure-captured original — so we install our capture as the
    # factory's current `create_llm_client` BEFORE running the patch,
    # the patch then captures our stub as `_orig`.
    captured: list[dict] = []

    def _capture_orig(provider, model, base_url=None, **kwargs):
        captured.append({
            "provider": provider, "model": model,
            "base_url": base_url, "kwargs": dict(kwargs),
        })
        return MagicMock()

    monkeypatch.setattr(_factory, "create_llm_client", _capture_orig)

    # Trigger the patch — wraps our _capture_orig as _orig.
    StockAnalyzer._patch_tradingagents_qwen()
    # Sanity: passthrough now includes the OR-required kwargs.
    assert "extra_body" in _oc._PASSTHROUGH_KWARGS
    assert "default_headers" in _oc._PASSTHROUGH_KWARGS

    # Invoke through the patched factory like upstream graph would.
    _factory.create_llm_client(
        provider="openrouter",
        model="deepseek/deepseek-v4-pro",
        base_url="https://openrouter.ai/api/v1",
    )
    assert captured, "factory wrapper never called the original"
    call = captured[-1]
    assert call["provider"] == "openrouter"
    eb = call["kwargs"].get("extra_body") or {}
    assert eb.get("provider", {}).get("order") == ["deepseek", "novita"], call
    assert eb["provider"]["allow_fallbacks"] is True
    headers = call["kwargs"].get("default_headers") or {}
    assert headers.get("X-Title") == "StockAI Terminal"
    assert headers.get("HTTP-Referer") == "https://stockai.example.com"

    # And again for the quick model id — should pick quick's provider_order.
    captured.clear()
    _factory.create_llm_client(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        base_url="https://openrouter.ai/api/v1",
    )
    quick_call = captured[-1]
    assert quick_call["kwargs"]["extra_body"]["provider"]["order"] == ["deepseek"], quick_call


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
