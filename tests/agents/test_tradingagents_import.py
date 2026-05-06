"""v1.0.2 P1-#1 smoke — real tradingagents import succeeds.

This test does NOT use the ``stub_tradingagents_graph`` fixture; it
exercises the real import chain so we can detect ``langgraph.prebuilt``
regressions early.  Skipped in environments without TradingAgents
installed (e.g. minimal CI), so the lab/cloud build catches it but a
local dev box without the upstream package doesn't fail spuriously.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_tradingagents_graph_module_imports():
    """``from tradingagents.graph.trading_graph import TradingAgentsGraph``
    must succeed in any environment that runs production analyzer code.

    Pre-v1.0.2 some envs hit ``ModuleNotFoundError: No module named
    'langgraph.prebuilt'`` because no requirements pin existed for
    langgraph. v1.0.2 added ``langgraph>=0.2,<2`` to requirements.txt
    so this guard catches future drift.
    """
    # Force a clean re-import path so a stub left over from another
    # test file (which ran with stub_tradingagents_graph) doesn't
    # mask a real-import failure here.
    for k in list(sys.modules):
        if k == "tradingagents.graph.trading_graph" or k == "langgraph.prebuilt":
            del sys.modules[k]

    try:
        mod = importlib.import_module("tradingagents.graph.trading_graph")
    except ModuleNotFoundError as e:
        if "tradingagents" in str(e):
            pytest.skip(f"tradingagents not installed: {e}")
        raise  # langgraph.prebuilt or other transitive — fail loud

    assert hasattr(mod, "TradingAgentsGraph"), (
        "tradingagents.graph.trading_graph imported but no "
        "TradingAgentsGraph symbol exposed"
    )
