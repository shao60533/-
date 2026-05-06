"""TC-MS-I1 ~ I6: Analyzer provider switching integration tests."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.agents.analyzer import StockAnalyzer


def _make_config(*, llm_provider=None, qwen_key="", gemini_key=""):
    """Build a minimal config dict for testing."""
    cfg = {
        "qwen": {
            "api_key": qwen_key,
            "model": "qwen-plus",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "gemini": {
            "api_key": gemini_key,
            "model": "gemini-2.5-flash",
            "deep_think_model": "gemini-2.5-flash",
            "thinking_level": "low",
        },
        "iteration": {"enabled": False},
    }
    if llm_provider is not None:
        cfg["llm_provider"] = llm_provider
    return cfg


# ── TC-MS-I1: active=qwen → graph uses qwen config ───────────────


@pytest.mark.integration
def test_analyzer_uses_qwen(monkeypatch, stub_tradingagents_graph):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    cfg = _make_config(qwen_key="sk-test", gemini_key="AIza-test")
    analyzer = StockAnalyzer(cfg)

    # v1.0.2 — fixture pre-stubs sys.modules so this works even if
    # langgraph.prebuilt isn't installed in the test env.
    stub_tradingagents_graph.return_value = MagicMock()
    analyzer._init_graph()

    assert any(k.startswith("qwen") for k in analyzer._graphs), list(analyzer._graphs)
    assert stub_tradingagents_graph.called


# ── TC-MS-I2: active=gemini → graph uses gemini config ────────────


@pytest.mark.integration
def test_analyzer_uses_gemini(monkeypatch, stub_tradingagents_graph):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    cfg = _make_config(qwen_key="sk-test", gemini_key="AIza-test")
    analyzer = StockAnalyzer(cfg)

    stub_tradingagents_graph.return_value = MagicMock()
    analyzer._init_graph()

    assert any(k.startswith("gemini") for k in analyzer._graphs), list(analyzer._graphs)


# ── TC-MS-I3: switch → second _init_graph creates new graph ──────


@pytest.mark.integration
def test_graph_cached_per_provider(monkeypatch, stub_tradingagents_graph):
    cfg = _make_config(qwen_key="sk-test", gemini_key="AIza-test")

    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    analyzer = StockAnalyzer(cfg)

    stub_tradingagents_graph.return_value = MagicMock()
    analyzer._init_graph()
    assert set(analyzer._graphs.keys()) == {"qwen@global"}

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    analyzer._init_graph()
    assert set(analyzer._graphs.keys()) == {"qwen@global", "gemini@global"}
    assert stub_tradingagents_graph.call_count == 2


# ── TC-MS-I4: switch back → cache hit, no new graph ──────────────


@pytest.mark.integration
def test_switch_back_hits_cache(monkeypatch, stub_tradingagents_graph):
    cfg = _make_config(qwen_key="sk-test", gemini_key="AIza-test")

    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    analyzer = StockAnalyzer(cfg)

    stub_tradingagents_graph.return_value = MagicMock()
    analyzer._init_graph()  # create qwen
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    analyzer._init_graph()  # create gemini
    assert stub_tradingagents_graph.call_count == 2

    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    analyzer._init_graph()  # should hit cache
    assert stub_tradingagents_graph.call_count == 2  # no new creation


# ── TC-MS-I5: gemini key empty → RuntimeError ────────────────────


@pytest.mark.integration
def test_gemini_missing_key_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    cfg = _make_config(gemini_key="")
    analyzer = StockAnalyzer(cfg)

    with pytest.raises(RuntimeError, match="gemini.*api_key"):
        analyzer._init_graph()


# ── TC-MS-I6: concurrent threads only create one graph ────────────


@pytest.mark.integration
def test_concurrent_init_single_creation(monkeypatch, stub_tradingagents_graph):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    cfg = _make_config(qwen_key="sk-test")
    analyzer = StockAnalyzer(cfg)

    call_count = {"n": 0}
    original_graph = MagicMock()

    def slow_init(*args, **kwargs):
        call_count["n"] += 1
        import time
        time.sleep(0.05)  # simulate slow init
        return original_graph

    stub_tradingagents_graph.side_effect = slow_init
    threads = [threading.Thread(target=analyzer._init_graph) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Wrap the rest in a no-op block so the original ``with`` body
    # indentation matches the new flat-fixture layout.
    if True:

        # Lock ensures only one creation despite 8 concurrent threads
        assert call_count["n"] == 1
        # v1.0.1: cache key suffix is @<user_id|global>.
        assert analyzer._graphs["qwen@global"] is original_graph
