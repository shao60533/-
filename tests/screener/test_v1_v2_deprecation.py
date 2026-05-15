"""hardening-iteration-v1 P3.1 [H12] — v1/v2 screeners are deprecated.

V3 (``screener/v3/pipeline.py``) is the canonical screener now: 14
guru agents, roundtable consensus, EOD-aware cache, async pipeline.
V1 / V2 remain importable for the migration window so the three live
call sites (web, telegram, main CLI) keep working until the v3 sync
wrapper PR flips them over. This suite locks down:

    1. v1 (screener/screener.py) emits a DeprecationWarning naming v3.
    2. v2 (screener/v2/__init__.py) emits a DeprecationWarning naming v3.
    3. Both modules' public symbols stay importable so the legacy
       call sites don't break overnight.
"""

from __future__ import annotations

import importlib
import sys
import warnings


def _reimport(name: str):
    if name in sys.modules:
        del sys.modules[name]
    return importlib.import_module(name)


def test_v1_screener_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        _reimport("stock_trading_system.screener.screener")
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deps, "v1 screener must emit DeprecationWarning on import"
    msg = str(deps[0].message)
    assert "v3" in msg, "warning must name v3 as the replacement"


def test_v2_screener_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        _reimport("stock_trading_system.screener.v2")
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deps, "v2 screener must emit DeprecationWarning on import"
    msg = str(deps[0].message)
    assert "v3" in msg


def test_v1_public_symbols_still_importable():
    """During the migration window the legacy module must keep
    exposing StockScreener so the three remaining call sites work."""
    mod = _reimport("stock_trading_system.screener.screener")
    assert hasattr(mod, "StockScreener")


def test_v2_public_symbols_still_importable():
    mod = _reimport("stock_trading_system.screener.v2")
    for name in ("ScreenerV2", "RegimeDetector", "Aggregator"):
        assert hasattr(mod, name), f"v2 lost public symbol {name!r}"


def test_v3_pipeline_is_the_canonical_target():
    """Defensive: the replacement must be importable from a fresh
    process — the deprecation warnings name it, so anyone reading
    them should be able to switch."""
    from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline
    assert ScreenerV3Pipeline is not None
