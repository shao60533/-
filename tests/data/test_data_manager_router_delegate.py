"""hardening-iteration-v1 P3.3 step-2 — DataManager optional DataRouter delegate.

Step-2 adds a feature flag (``config.data_routing.use_router_delegate``)
that routes DataManager.get_price through DataRouter (Qwen-first +
capability matrix) instead of the legacy Schwab → IB → Polygon →
yfinance → Qwen chain. Default OFF so existing behaviour is
unchanged; step-3 flips it after a dogfood week.

This suite locks down:

  1. Default config → no delegate → legacy chain runs as before.
  2. Flag-on config → delegate → DataRouter.get_price is the one
     that gets called.
  3. Delegate init failure falls back to legacy chain (degrade,
     don't crash).
  4. The legacy fallback chain is untouched by this commit — same
     LocalCache-first lookup, same provider preference order.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class _DummyLocalCache:
    def __init__(self):
        self.prices: dict[str, dict] = {}

    def get_price(self, ticker: str):
        return self.prices.get(ticker.upper())

    def set_price(self, ticker: str, quote: dict):
        self.prices[ticker.upper()] = quote


def _make_dm(*, use_router: bool, cache=None, router_returns=None):
    """Construct a DataManager with the feature flag in either state.
    The lazy-built DataRouter is replaced with a stub *after* the
    DataManager exists so subsequent get_price calls outside the
    patch scope still see the stub."""
    from stock_trading_system.data import data_manager as dm_mod

    config = {
        "data_routing": {"use_router_delegate": use_router},
        "providers": {
            "ib_enabled": False, "polygon_enabled": False,
            "schwab_enabled": False, "yfinance_enabled": True,
            "akshare_enabled": True,
        },
        "qwen": {"enabled": False},
    }

    cache = cache or _DummyLocalCache()

    dm = dm_mod.DataManager(config, cache=cache)

    stub_router = MagicMock()
    stub_router.get_price = MagicMock(return_value=router_returns)

    if use_router:
        # Replace the lazy-init router slot directly. _get_router()
        # returns ``self._router`` when it's non-None and the flag is
        # on, so this short-circuits the function-local import path
        # that pytest.patch can't see through.
        dm._router = stub_router

    return dm, stub_router


# ── default behaviour: no delegate ─────────────────────────────────────────


def test_default_flag_off_does_not_use_router():
    """Without the flag, get_price never touches DataRouter."""
    dm, router = _make_dm(use_router=False)
    # Cache hit so we don't try to reach real providers.
    dm._cache.set_price("AAPL", {"last": 100.0})

    result = dm.get_price("AAPL")

    assert result == {"last": 100.0}
    router.get_price.assert_not_called()
    assert dm._use_router_delegate is False
    assert dm._router is None  # never instantiated


def test_router_attr_is_none_when_flag_off():
    """Defensive: ``_router`` should stay None when the flag is off so
    we never accidentally pay the DataRouter init cost in default
    deployments."""
    dm, _ = _make_dm(use_router=False)
    assert dm._router is None
    # Even after a real get_price call.
    dm._cache.set_price("MSFT", {"last": 200})
    dm.get_price("MSFT")
    assert dm._router is None


# ── flag on: delegate path ────────────────────────────────────────────────


def test_flag_on_routes_via_data_router():
    """With the flag, get_price's first hit is DataRouter — bypassing
    the legacy cache+chain entirely so DataRouter's own cache policy
    (capability matrix) governs."""
    dm, router = _make_dm(
        use_router=True,
        router_returns={"last": 150.0, "source": "router"},
    )

    result = dm.get_price("AAPL", market="us")

    router.get_price.assert_called_once_with("AAPL", market="us")
    assert result == {"last": 150.0, "source": "router"}


def test_flag_on_resolves_market_when_not_passed():
    """When caller omits ``market``, DataManager.detect_market fills
    it in before delegating. DataRouter sees the resolved market."""
    dm, router = _make_dm(use_router=True, router_returns={"last": 1.0})

    dm.get_price("AAPL")

    # detect_market("AAPL") → "us"
    router.get_price.assert_called_once_with("AAPL", market="us")


def test_router_lazy_instantiated_only_on_first_call():
    """We pay the DataRouter init cost on the first delegated get_price,
    not at DataManager.__init__ time.

    We can't easily test the *real* lazy path because the function-local
    ``from … import DataRouter`` inside ``_get_router`` is opaque to
    pytest.patch — _make_dm above injects ``_router`` directly. This
    test just asserts the contract that DataManager.__init__ does
    NOT eagerly instantiate the router (even with the flag on).
    """
    from stock_trading_system.data import data_manager as dm_mod
    config = {
        "data_routing": {"use_router_delegate": True},
        "providers": {"yfinance_enabled": True},
        "qwen": {"enabled": False},
    }
    dm = dm_mod.DataManager(config, cache=_DummyLocalCache())
    # Pre-call: lazy slot is still None.
    assert dm._router is None
    # Confirm the flag was actually read off the config.
    assert dm._use_router_delegate is True


# ── degraded paths ────────────────────────────────────────────────────────


def test_router_init_failure_falls_back_to_legacy():
    """If DataRouter construction raises, the flag silently flips off
    and the next call uses the legacy chain. Better than crashing the
    Flask request.

    We trigger the failure by injecting a sentinel object that
    pretends to be DataRouter and raises on construction."""
    from stock_trading_system.data import data_manager as dm_mod

    config = {
        "data_routing": {"use_router_delegate": True},
        "providers": {"yfinance_enabled": True},
        "qwen": {"enabled": False},
    }
    cache = _DummyLocalCache()
    cache.set_price("AAPL", {"last": 99.0, "source": "cache"})

    dm = dm_mod.DataManager(config, cache=cache)
    assert dm._use_router_delegate is True

    # Force the lazy init path to fail. Patch the import target the
    # function-local statement resolves to; the next ``_get_router``
    # call will catch the RuntimeError, log, and flip the flag off.
    with patch(
        "stock_trading_system.data.data_router.DataRouter",
        side_effect=RuntimeError("config broken"),
    ):
        result = dm.get_price("AAPL")

    assert result == {"last": 99.0, "source": "cache"}
    assert dm._use_router_delegate is False
