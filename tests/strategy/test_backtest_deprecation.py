"""hardening-iteration-v1 P3.2 [H13] — strategy.backtest is deprecated.

The legacy ``stock_trading_system.strategy.backtest`` module had three
implementation differences with ``stock_trading_system.strategy.backtester``
that nobody caught:

    * field name: total_return_pct  vs  total_return
    * annualisation: 365  vs  252 (trading days)
    * slippage: 1%  vs  0 (parameterised)
    * RSI: SMA  vs  Wilder EWM

The web entrypoints currently still bind to the legacy module
(``web/app.py:2978/2995``). Until the parity test below (paired with
the schema-aligning shim in BacktestEngine) gates the migration, both
modules co-exist. The deprecation warning surfaces during import so
future contributors notice and route new call sites to BacktestEngine.
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest


def _reimport_backtest():
    """Force a fresh import of the deprecated module so the warning
    fires on each test (Python caches subsequent imports)."""
    if "stock_trading_system.strategy.backtest" in sys.modules:
        del sys.modules["stock_trading_system.strategy.backtest"]
    return importlib.import_module("stock_trading_system.strategy.backtest")


def test_legacy_backtest_emits_deprecation_warning():
    """First import of the legacy module surfaces a DeprecationWarning
    naming the replacement (BacktestEngine)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        _reimport_backtest()

    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deps, "expected a DeprecationWarning on import"
    msg = str(deps[0].message)
    assert "deprecated" in msg.lower()
    assert "BacktestEngine" in msg, \
        "warning must name the replacement so contributors can migrate"


def test_legacy_module_still_functional():
    """The deprecated module must keep working for the migration window
    — callers shouldn't break overnight just because we added a
    warning. Smoke-check the public surface stays callable."""
    bt = _reimport_backtest()
    # The two key public symbols web/app.py imports today.
    assert hasattr(bt, "Backtester")
    assert hasattr(bt, "BacktestResult")
    assert hasattr(bt, "BacktestTrade")


def test_new_module_is_the_canonical_one():
    """Defensive: the replacement module exposes BacktestEngine + run().
    The migration target must be importable from a clean process."""
    from stock_trading_system.strategy import backtester
    assert hasattr(backtester, "BacktestEngine")
    assert hasattr(backtester.BacktestEngine, "run")
