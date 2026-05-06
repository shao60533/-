"""Shared fixtures for tests/agents/.

v1.0.2 (P1-#1) — ``stub_tradingagents_graph`` lives here so every
agents test that needs to exercise ``StockAnalyzer._init_graph``
without a real ``tradingagents.graph.trading_graph`` import works
in environments where transitive deps are missing
(notably ``langgraph.prebuilt``).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_tradingagents_graph(monkeypatch):
    """Pre-stub the tradingagents import chain in ``sys.modules``.

    ``unittest.mock.patch('tradingagents.graph.trading_graph.TradingAgentsGraph')``
    resolves the dotted path AT call time, which means the import chain
    runs first; if any step fails (e.g. ``langgraph.prebuilt`` missing),
    the patch fails before the test body executes. This fixture pre-
    injects fake modules into ``sys.modules`` carrying the symbols the
    analyzer expects, so ``from tradingagents.graph.trading_graph import
    TradingAgentsGraph`` returns our MagicMock without ever loading the
    real chain.

    Yields the ``TradingAgentsGraph`` stub class so tests can stub the
    return value:

        def test_foo(stub_tradingagents_graph):
            stub_tradingagents_graph.return_value = MagicMock()
            analyzer._init_graph()
            assert stub_tradingagents_graph.called
    """
    # ALWAYS replace these modules with stubs (don't skip if they
    # exist) — earlier tests in the run may have imported the real
    # ones, leaving sys.modules with the real TradingAgentsGraph
    # class. Without forced replacement, ``patch`` would resolve to
    # the real class and tests would fail under ordering.
    saved: dict[str, object] = {}
    for mod_name in (
        "langgraph",
        "langgraph.prebuilt",
        "tradingagents.graph.trading_graph",
        "tradingagents.default_config",
    ):
        saved[mod_name] = sys.modules.get(mod_name)
        stub = types.ModuleType(mod_name)
        if mod_name == "tradingagents.graph.trading_graph":
            stub.TradingAgentsGraph = MagicMock(name="TradingAgentsGraph_stub")
        if mod_name == "tradingagents.default_config":
            stub.DEFAULT_CONFIG = {}
        sys.modules[mod_name] = stub

    yield sys.modules["tradingagents.graph.trading_graph"].TradingAgentsGraph

    # Restore originals (or pop if originally absent).
    for mod_name, original in saved.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original
