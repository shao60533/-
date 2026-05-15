"""hardening-iteration-v1 P2.1 + P2.2 — LocalCache.set ttl & registration.

Pre-P2.1: ``LocalCache.set`` did not accept a ``ttl=`` kwarg; v3 guru
cache passed it and crashed inside a swallowed except, so the cache hit
rate stayed at 0% silently. Pre-P2.2: unknown categories silently
inherited "no TTL = forever", letting any new code leak entries into
the cache indefinitely.

This suite locks down:
    1. set(category, key, value, ttl=N) is accepted (no TypeError).
    2. The ttl override controls expiry vs the category default.
    3. Unknown categories are rejected (write returns silently +
       logs warning); writes are not persisted.
    4. unsafe_default_ttl=N opts in unknown categories at runtime.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from stock_trading_system.data.local_cache import LocalCache, _DEFAULT_TTL


@pytest.fixture
def cache(tmp_path):
    return LocalCache(str(tmp_path / "cache.db"))


# ── P2.1: ttl kwarg accepted + honored ─────────────────────────────────────


def test_set_accepts_ttl_kwarg(cache):
    """The v3-guru caller pattern: ttl=<seconds>."""
    # Should NOT raise TypeError as the pre-P2.1 signature did.
    cache.set("price_quote", "AAPL", {"last": 150.0}, ttl=60)
    assert cache.get("price_quote", "AAPL") == {"last": 150.0}


def test_per_entry_ttl_overrides_category_default(cache):
    """ttl=1 second on a category with 60s default → entry should expire
    after 1.1 seconds (or rather, the category default is irrelevant)."""
    cache.set("price_quote", "TINY_TTL", {"v": 1}, ttl=1)
    # immediately readable
    assert cache.get("price_quote", "TINY_TTL") == {"v": 1}
    time.sleep(1.2)
    assert cache.get("price_quote", "TINY_TTL") is None


def test_no_ttl_falls_back_to_category_default(cache):
    """Without explicit ttl, set uses _DEFAULT_TTL[category]."""
    cache.set("price_quote", "DEFAULT", {"v": 2})
    assert cache.get("price_quote", "DEFAULT") == {"v": 2}
    # price_quote default is 60s; entry is still fresh.


# ── P2.2: unknown category rejected ───────────────────────────────────────


def test_unknown_category_rejected(cache, caplog):
    """set() into an unregistered category is a no-op + warning."""
    with caplog.at_level("WARNING"):
        cache.set("ghost_category", "k", "v")
    # No row should have been written.
    assert cache.get("ghost_category", "k") is None
    assert any("unknown category" in r.message.lower() for r in caplog.records)


def test_unsafe_default_ttl_opts_in_category(cache):
    """Caller can register dev/experimental categories at runtime."""
    cache.set("dev_temp", "k", {"value": 42}, unsafe_default_ttl=10)
    assert cache.get("dev_temp", "k") == {"value": 42}


def test_registered_v3_categories_accept_writes(cache):
    """P2.2 added guru_signal_v3 / regime / nl_parse / roundtable.
    Each should accept writes without unsafe_default_ttl."""
    for cat in ("guru_signal_v3", "regime", "nl_parse", "roundtable"):
        cache.set(cat, "k", {"cat": cat})
        assert cache.get(cat, "k") == {"cat": cat}


# ── P2.2 default-ttl table coverage ────────────────────────────────────────


def test_default_ttl_table_includes_v3_categories():
    """Defensive: _DEFAULT_TTL is the canonical registry, and the v3
    categories must always live here so deployments don't lose hits
    when a new node spins up without the runtime dev-register call."""
    for cat in ("guru_signal_v3", "regime", "nl_parse", "roundtable"):
        assert cat in _DEFAULT_TTL, f"missing v3 category {cat!r} in _DEFAULT_TTL"
