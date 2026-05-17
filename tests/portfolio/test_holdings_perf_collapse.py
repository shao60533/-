"""Tests for the 2026-05-16 dashboard perf collapse.

The dashboard / portfolio summary / portfolio allocation surfaces all
used to call ``pm.get_holdings()`` separately. With three concurrent
requests from a single user, each call triggered a fresh provider quote
fetch — on Railway with cold Schwab sockets this drove 30–70s p95 on
/api/portfolio/*. The fix moves derivation into pure helpers
(``compute_pnl_from_holdings`` / ``compute_allocation_from_holdings``)
and adds a 45s user-keyed cross-request holdings cache invalidated on
every mutation (buy / sell / remove / update_cost).

Tests covered here:
    1. ``compute_pnl_from_holdings`` derives the right totals + matches
       the live ``get_pnl`` output.
    2. ``compute_allocation_from_holdings`` weights add up to 1 and the
       ordering matches the live ``get_allocation``.
    3. Cross-request holdings cache: a second call within TTL reuses
       the result and never re-hits DataManager.
    4. ``add_position`` invalidates the cache so the next read sees
       the new ticker.
    5. ``sell_position`` invalidates the cache.
    6. ``remove_position`` invalidates the cache.
    7. ``update_cost`` invalidates the cache.
    8. Price fallback: when the batch+per-ticker fetch return nothing,
       holdings annotate ``price_source="cost"`` and ``price_stale=True``
       instead of dropping the row.
"""

from __future__ import annotations

import pytest

from stock_trading_system.portfolio.manager import (
    PortfolioManager, _invalidate_user_holdings_cache,
    _read_user_holdings_cache,
)


class _CountingDataManager:
    """DataManager stub that records every batch / per-ticker call.

    Returns a fixed price per ticker so PnL math is deterministic.
    """

    def __init__(self, *_, **__):
        self.batch_calls = 0
        self.per_ticker_calls = 0
        self.prices = {"AAPL": 200.0, "MSFT": 400.0}

    def get_prices_batch(self, tickers, market=None):
        self.batch_calls += 1
        return {t: {"last": self.prices.get(t, 0)} for t in tickers}

    def get_price(self, ticker, market=None):
        self.per_ticker_calls += 1
        return {"last": self.prices.get(ticker, 0)}


@pytest.fixture
def pm(tmp_path):
    """Build a PortfolioManager wired to an isolated tmp db + counting DM."""
    db_path = tmp_path / "portfolio.db"
    dm = _CountingDataManager()
    manager = PortfolioManager(str(db_path), data_manager=dm)
    # Each test starts with a clean user-level cache so prior tests can't
    # pollute the assertions.
    _invalidate_user_holdings_cache(1)
    _invalidate_user_holdings_cache(2)
    return manager, dm


# ── helpers ─────────────────────────────────────────────────────────────


def _seed_two_positions(pm: PortfolioManager, user_id: int = 1):
    pm.add_position("AAPL", 10, 150.0, user_id=user_id)
    pm.add_position("MSFT", 5, 380.0, user_id=user_id)


# ── 1 + 2 — pure derivation helpers ─────────────────────────────────────


def test_compute_pnl_from_holdings_matches_get_pnl(pm):
    manager, _ = pm
    _seed_two_positions(manager)
    holdings = manager.get_holdings(user_id=1)

    pure = PortfolioManager.compute_pnl_from_holdings(holdings)
    live = manager.get_pnl(user_id=1)

    # Same shape, same numbers — the live path now delegates to the pure
    # helper so any drift here means the refactor broke something.
    assert pure == live
    # Sanity: 10 AAPL @ cost 150 → mv 2000, cost 1500, pnl +500
    #        5  MSFT @ cost 380 → mv 2000, cost 1900, pnl +100
    assert pure["total_value"] == pytest.approx(4000.0)
    assert pure["total_cost"] == pytest.approx(3400.0)
    assert pure["total_pnl"] == pytest.approx(600.0)
    assert pure["positions"] == 2


def test_compute_allocation_from_holdings_matches_get_allocation(pm):
    manager, _ = pm
    _seed_two_positions(manager)
    holdings = manager.get_holdings(user_id=1)

    pure = PortfolioManager.compute_allocation_from_holdings(holdings)
    live = manager.get_allocation(user_id=1)

    assert pure == live
    assert len(pure) == 2
    # 2000 + 2000 → weight 0.5 each
    assert all(p["weight"] == pytest.approx(0.5) for p in pure)
    assert sum(p["weight"] for p in pure) == pytest.approx(1.0)
    # Tied market_value → AAPL and MSFT both present; ticker order is
    # stable on tied weights via the .sort() reverse=True path.
    tickers = {p["ticker"] for p in pure}
    assert tickers == {"AAPL", "MSFT"}


# ── 3 — cross-request cache reuse ───────────────────────────────────────


def test_get_holdings_uses_cache_within_ttl(pm):
    manager, dm = pm
    _seed_two_positions(manager)

    # First call populates the cache; batch_calls should rise.
    _ = manager.get_holdings(user_id=1)
    assert dm.batch_calls == 1

    # Second call within TTL must NOT hit DataManager — this is the
    # whole point of the perf collapse fix.
    _ = manager.get_holdings(user_id=1)
    assert dm.batch_calls == 1, (
        "second get_holdings inside TTL triggered another batch fetch — "
        "user-level cache is broken"
    )

    # Repeated derivation paths (get_pnl / get_allocation) also reuse.
    manager.get_pnl(user_id=1)
    manager.get_allocation(user_id=1)
    assert dm.batch_calls == 1


# ── 4–7 — mutations invalidate the cache ────────────────────────────────


def test_add_position_invalidates_cache(pm):
    manager, dm = pm
    _seed_two_positions(manager)
    manager.get_holdings(user_id=1)
    assert dm.batch_calls == 1
    # Cache populated; entry exists.
    assert _read_user_holdings_cache(1) is not None

    # New buy must invalidate immediately.
    manager.add_position("NVDA", 2, 700.0, user_id=1)
    assert _read_user_holdings_cache(1) is None

    # Next read sees the new ticker AND re-hits the provider.
    fresh = manager.get_holdings(user_id=1)
    tickers = {h["ticker"] for h in fresh}
    assert "NVDA" in tickers
    assert dm.batch_calls == 2


def test_sell_position_invalidates_cache(pm):
    manager, _ = pm
    _seed_two_positions(manager)
    manager.get_holdings(user_id=1)
    assert _read_user_holdings_cache(1) is not None

    manager.sell_position("AAPL", 10, 220.0, user_id=1)
    assert _read_user_holdings_cache(1) is None


def test_remove_position_invalidates_cache(pm):
    manager, _ = pm
    _seed_two_positions(manager)
    manager.get_holdings(user_id=1)
    assert _read_user_holdings_cache(1) is not None

    manager.remove_position("AAPL", user_id=1)
    assert _read_user_holdings_cache(1) is None


def test_update_cost_invalidates_cache(pm):
    manager, _ = pm
    _seed_two_positions(manager)
    manager.get_holdings(user_id=1)
    assert _read_user_holdings_cache(1) is not None

    manager.update_cost("AAPL", 160.0, user_id=1)
    assert _read_user_holdings_cache(1) is None


# ── 8 — price fallback annotations ──────────────────────────────────────


class _NoPriceDataManager:
    """Pretends both batch and per-ticker quotes returned nothing."""

    def __init__(self, *_, **__):
        pass

    def get_prices_batch(self, tickers, market=None):
        return {}

    def get_price(self, ticker, market=None):
        return None


def test_holdings_falls_back_to_cost_when_provider_returns_nothing(tmp_path):
    """When upstream goes dark, holdings still render — annotated as stale.

    Before the perf collapse, a missing price made current_price=0 and
    surfaced as a -100% pnl row that the UI couldn't distinguish from a
    real loss. Now ``price_source="cost"`` + ``price_stale=True`` lets
    the React island show a "价格降级" hint instead.
    """
    _invalidate_user_holdings_cache(99)
    manager = PortfolioManager(
        str(tmp_path / "p.db"),
        data_manager=_NoPriceDataManager(),
    )
    manager.add_position("AAPL", 10, 150.0, user_id=99)
    holdings = manager.get_holdings(user_id=99)
    assert len(holdings) == 1
    h = holdings[0]
    assert h["price_source"] == "cost"
    assert h["price_stale"] is True
    # Cost-basis fallback → current_price == avg_cost → pnl == 0
    assert h["current_price"] == pytest.approx(150.0)
    assert h["pnl"] == pytest.approx(0.0)
