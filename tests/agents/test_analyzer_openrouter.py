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


# ``stub_tradingagents_graph`` fixture moved to tests/agents/conftest.py
# in v1.0.2 (P1-#1) so test_analyzer_provider_switch.py can use it too.


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
def test_graph_cache_key_changes_on_deep_preset_swap(monkeypatch, stub_tradingagents_graph):
    """The cache key for OR is ``openrouter:<deep_id>:<quick_id>@<scope>``
    so swapping the active deep preset (UI / yaml) creates a fresh
    TradingAgents graph with the new model bindings instead of
    silently reusing the old one.

    v1.0.1 P1-D — uses the ``stub_tradingagents_graph`` fixture so the
    test runs in environments where ``tradingagents.graph.trading_graph``
    can't be imported directly (e.g. langgraph.prebuilt missing in CI).
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config(deep_id="deepseek-v4-pro")
    analyzer = StockAnalyzer(cfg)

    # ``stub_tradingagents_graph`` is the MagicMock that replaced the
    # real TradingAgentsGraph class — use it directly as the patch.
    stub_tradingagents_graph.return_value = MagicMock()
    analyzer._init_graph()

    cache_keys_before = list(analyzer._graphs.keys())
    assert cache_keys_before == ["openrouter:deepseek-v4-pro:deepseek-v4-flash@global"]

    # Swap active.deep — mutating the live config dict mirrors what
    # /api/settings/openrouter/active POST + save_config does after
    # _reset_config_dependent_singletons clears the analyzer.
    analyzer._config["openrouter"]["active"]["deep"] = "gemini-3.1-pro"

    analyzer._init_graph()

    cache_keys_after = list(analyzer._graphs.keys())
    assert "openrouter:gemini-3.1-pro:deepseek-v4-flash@global" in cache_keys_after
    assert len(cache_keys_after) == 2


@pytest.mark.integration
def test_concurrent_analyze_users_dont_share_graph(
    monkeypatch, stub_tradingagents_graph,
):
    """v1.0.2 P1-#2 — concurrent analyze() calls with different
    user_ids must each see their own graph reference; the analyzer's
    cache key is per-user so they get DIFFERENT graphs.

    Pre-v1.0.2 ``self._active_user_id`` + ``self._graph`` were shared
    mutable per-call attrs that two concurrent threads could overwrite.
    Now ``_init_graph(user_id, depth) -> graph`` returns locally and
    callers hold local references — race-free.
    """
    import threading

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    # Each call to TradingAgentsGraph(...) gets a unique sentinel so
    # we can prove the two users got different graph instances.
    sentinels = []

    def factory(*args, **kwargs):
        s = MagicMock(name=f"graph_{len(sentinels)}")
        sentinels.append(s)
        # Sleep inside graph init to maximize the chance of
        # interleaved execution between threads.
        import time as _t
        _t.sleep(0.05)
        return s

    stub_tradingagents_graph.side_effect = factory

    results: dict[int, object] = {}

    def run(uid: int):
        # Each thread inherits the parent's contextvar context but
        # its own subtree — _init_graph sets _OR_ROUTING_CTX inside
        # the call, so two threads don't see each other's value.
        results[uid] = analyzer._init_graph(user_id=uid)

    t1 = threading.Thread(target=run, args=(42,))
    t2 = threading.Thread(target=run, args=(99,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    g_42 = results[42]
    g_99 = results[99]
    assert g_42 is not g_99, "concurrent users should NOT share a graph"
    # Cache reflects two distinct entries.
    keys = set(analyzer._graphs.keys())
    assert any(k.endswith("@42") for k in keys), keys
    assert any(k.endswith("@99") for k in keys), keys
    # Verify each user's local return matches the cache entry under
    # their scope — proves the local reference is stable even if
    # ``self._graph`` got overwritten by the other thread mid-flight.
    for uid in (42, 99):
        per_user_keys = [k for k in keys if k.endswith(f"@{uid}")]
        assert len(per_user_keys) == 1
        assert analyzer._graphs[per_user_keys[0]] is results[uid]


@pytest.mark.integration
def test_init_graph_smoke_when_langgraph_unavailable(monkeypatch, stub_tradingagents_graph):
    """v1.0.1 P1-D smoke — StockAnalyzer._init_graph completes (does
    NOT raise) in an environment where the real
    ``tradingagents.graph.trading_graph`` module would fail to import
    due to a missing transitive dependency (e.g. langgraph.prebuilt).

    The fixture pre-injects a stub module so ``from tradingagents.
    graph.trading_graph import TradingAgentsGraph`` returns our
    MagicMock without ever loading the real chain.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    stub_tradingagents_graph.return_value = MagicMock()
    # Should not raise even if langgraph.prebuilt isn't installed —
    # the stub fixture pre-loads sys.modules to short-circuit the
    # real import chain.
    analyzer._init_graph()

    assert stub_tradingagents_graph.called, (
        "TradingAgentsGraph stub was never invoked — _init_graph "
        "didn't reach the construction call"
    )
    assert len(analyzer._graphs) == 1


@pytest.mark.integration
def test_init_graph_uses_per_user_provider_and_cache_scope(
    monkeypatch, stub_tradingagents_graph,
):
    """v1.0.1 P1-B fix — analyzer.analyze(user_id=N) makes _init_graph
    resolve the provider with that user's scope (router honors
    user_settings.llm_provider) AND scopes the graph cache under the
    user id, so user A on qwen and user B on openrouter never share
    a graph.

    v1.0.3 — converted from raw ``patch("tradingagents.graph...")`` to
    the ``stub_tradingagents_graph`` fixture so it runs in environments
    without ``langgraph.prebuilt`` (the patch path was resolving the
    real import chain at test-collection time).

    Verifies:
    - cache_key for user_id=42 + global LLM_PROVIDER=openrouter ends
      with '@42' rather than the legacy unscoped key.
    - cache_key for user_id=None still ends with '@global'.
    - Two different user ids produce two separate cache entries with
      distinct graph instances.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cfg = _or_config()
    analyzer = StockAnalyzer(cfg)

    # Each call to TradingAgentsGraph(...) returns a distinct sentinel
    # so we can prove different users got different graph instances.
    graph_instances: list = []

    def _new_graph(*args, **kwargs):
        g = MagicMock(name=f"graph_{len(graph_instances)}")
        graph_instances.append(g)
        return g

    stub_tradingagents_graph.side_effect = _new_graph

    # First init — user A.
    graph_a = analyzer._init_graph(user_id=42)
    assert graph_a is not None, "_init_graph should return the graph"
    keys_a = list(analyzer._graphs.keys())
    assert any(k.endswith("@42") for k in keys_a), keys_a

    # Second init — user B.
    graph_b = analyzer._init_graph(user_id=99)
    keys_b = list(analyzer._graphs.keys())
    assert any(k.endswith("@99") for k in keys_b), keys_b
    assert len(keys_b) == 2, "expected 2 cache entries for 2 different users"
    assert graph_b is not graph_a, "different users must get different graphs"

    # Third init — no user_id (legacy direct caller). Maps to @global.
    graph_g = analyzer._init_graph()
    keys_c = list(analyzer._graphs.keys())
    assert any(k.endswith("@global") for k in keys_c), keys_c
    assert len(keys_c) == 3
    assert graph_g is not graph_a and graph_g is not graph_b


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

    # v1.0.2 — the patch wrapper reads OR routing from the
    # ``_OR_ROUTING_CTX`` ContextVar, not from get_config(). Set it
    # explicitly here to mirror what _init_graph does in production.
    from stock_trading_system.agents import analyzer as _analyzer_mod
    from tradingagents.llm_clients import factory as _factory
    from tradingagents.llm_clients import openai_client as _oc

    routing = {
        "deep_model": "deepseek/deepseek-v4-pro",
        "quick_model": "deepseek/deepseek-v4-flash",
        "deep_provider_order": ["deepseek", "novita"],
        "quick_provider_order": ["deepseek"],
        "headers": {
            "HTTP-Referer": "https://stockai.example.com",
            "X-Title": "StockAI Terminal",
        },
    }
    token = _analyzer_mod._OR_ROUTING_CTX.set(routing)

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

    # Cleanup ContextVar token (autouse fixture handles env restore;
    # we own the ContextVar life-cycle in this test).
    _analyzer_mod._OR_ROUTING_CTX.reset(token)


@pytest.mark.integration
def test_or_factory_passthrough_when_routing_ctx_unset(monkeypatch):
    """v1.0.2 P1-#3 — when ``_OR_ROUTING_CTX`` is not set (e.g. legacy
    caller, or a non-OR call to the factory), the wrapper must pass
    through to the original ``create_llm_client`` UNCHANGED. No
    extra_body / default_headers should be injected from a stale
    global.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    from stock_trading_system.agents import analyzer as _analyzer_mod
    from tradingagents.llm_clients import factory as _factory
    from tradingagents.llm_clients import openai_client as _oc

    # Make sure the ctx is unset (autouse fixtures don't touch it).
    assert _analyzer_mod._OR_ROUTING_CTX.get() is None

    captured: list[dict] = []

    def _capture(provider, model, base_url=None, **kwargs):
        captured.append({"provider": provider, "model": model,
                          "kwargs": dict(kwargs)})
        return MagicMock()

    monkeypatch.setattr(_factory, "create_llm_client", _capture)

    StockAnalyzer._patch_tradingagents_qwen()
    _factory.create_llm_client(
        provider="openrouter",
        model="deepseek/deepseek-v4-pro",
        base_url="https://openrouter.ai/api/v1",
    )
    call = captured[-1]
    # Wrapper saw OR provider but ContextVar was None → no inject.
    assert "extra_body" not in call["kwargs"], call
    assert "default_headers" not in call["kwargs"], call


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
