"""LocalCache unit tests — LC-2.1.* and LH-2.2.* from test plan."""

from __future__ import annotations

import os
import threading
import time

import pandas as pd
import pytest

from stock_trading_system.data.local_cache import LocalCache


@pytest.fixture
def cache(tmp_path):
    # Shorten TTLs for tests where we want to watch expiry behavior.
    cfg = {"data_routing": {"cache_ttl": {
        "price_quote": 60,
        "daily_bars": 43200,
        "minute_bars": 300,
        "fundamentals": 86400,
        "news": 3600,
    }}}
    return LocalCache(str(tmp_path / "cache.db"), config=cfg)


# ── LC-2.1.1 / 2 write and read ───────────────────────────────────────────────


def test_price_set_and_get(cache):
    cache.set_price("AAPL", {"last": 150.0, "open": 148.0})
    got = cache.get_price("AAPL")
    assert got["last"] == 150.0


def test_case_insensitive_ticker(cache):
    cache.set_price("aapl", {"last": 150})
    assert cache.get_price("AAPL") == {"last": 150}


# ── LC-2.1.3 TTL expiry ───────────────────────────────────────────────────────


def test_price_ttl_expiry(tmp_path):
    # 1-second TTL to exercise expiry fast
    cfg = {"data_routing": {"cache_ttl": {"price_quote": 1}}}
    cache = LocalCache(str(tmp_path / "cache.db"), config=cfg)
    cache.set_price("AAPL", {"last": 150})
    assert cache.get_price("AAPL") is not None
    time.sleep(2.2)
    assert cache.get_price("AAPL") is None


# ── LC-2.1.4 / 5 / 6 / 7 category-specific TTLs ──────────────────────────────


def test_multi_category_ttls_independent(tmp_path):
    cfg = {"data_routing": {"cache_ttl": {
        "price_quote": 1, "fundamentals": 100,
    }}}
    cache = LocalCache(str(tmp_path / "cache.db"), config=cfg)
    cache.set_price("AAPL", {"last": 150})
    cache.set_fundamentals("AAPL", {"pe": 30})
    time.sleep(2.2)
    # price TTL (1s) expired, fundamentals (100s) still valid
    assert cache.get_price("AAPL") is None
    assert cache.get_fundamentals("AAPL") == {"pe": 30}


# ── LC-2.1.8 keys independent ────────────────────────────────────────────────


def test_tickers_independent(cache):
    cache.set_price("AAPL", {"last": 150})
    cache.set_price("TSLA", {"last": 220})
    assert cache.get_price("AAPL") == {"last": 150}
    assert cache.get_price("TSLA") == {"last": 220}


# ── LC-2.1.9 overwrite ───────────────────────────────────────────────────────


def test_overwrite_keeps_latest(cache):
    cache.set_price("AAPL", {"last": 150})
    cache.set_price("AAPL", {"last": 155})
    assert cache.get_price("AAPL") == {"last": 155}


# ── LC-2.1.10 large payloads (DataFrame) ─────────────────────────────────────


def test_dataframe_round_trip(cache):
    df = pd.DataFrame({
        "open": [1.0, 2.0, 3.0],
        "high": [1.1, 2.1, 3.1],
        "low": [0.9, 1.9, 2.9],
        "close": [1.05, 2.05, 3.05],
        "volume": [1000, 2000, 3000],
    }, index=pd.date_range("2026-01-01", periods=3, freq="D"))
    cache.set_bars("AAPL", "1mo", "1d", df)
    back = cache.get_bars("AAPL", "1mo", "1d")
    assert back is not None
    # P2.3: payloads round-trip via JSON (was: pickle). JSON doesn't
    # carry pandas-specific metadata (DatetimeIndex.freq), and read_json
    # coerces whole-number floats back to int. We compare logical
    # equality — values match within numerical tolerance, schema is
    # preserved — rather than full pickle-level frame identity.
    pd.testing.assert_frame_equal(
        back, df, check_freq=False, check_dtype=False,
    )


# ── LC-2.1.11 configurable TTL ───────────────────────────────────────────────


def test_ttl_from_config_applied(tmp_path):
    cfg = {"data_routing": {"cache_ttl": {"daily_bars": 3600}}}
    cache = LocalCache(str(tmp_path / "cache.db"), config=cfg)
    assert cache.ttl_for("daily_bars") == 3600


# ── LC-2.1.12 cleanup ────────────────────────────────────────────────────────


def test_cleanup_removes_expired(tmp_path):
    # TTL 1s + sleep 2.2s to safely clear second-precision boundaries.
    cfg = {"data_routing": {"cache_ttl": {"price_quote": 1}}}
    cache = LocalCache(str(tmp_path / "cache.db"), config=cfg)
    cache.set_price("AAPL", {"last": 150})
    cache.set_news("AAPL", [{"title": "hi"}])  # news TTL 3600, won't expire
    time.sleep(2.2)
    removed = cache.cleanup()
    assert removed >= 1
    assert cache.get_price("AAPL") is None
    assert cache.get_news("AAPL") is not None


# ── LC-2.1.13 miss returns None without raising ──────────────────────────────


def test_missing_key_returns_none(cache):
    assert cache.get_price("DOESNOTEXIST") is None
    assert cache.get_fundamentals("X") is None
    assert cache.get_news("X") is None
    assert cache.get_bars("X", "1mo", "1d") is None


# ── LC-2.1.14 concurrency ────────────────────────────────────────────────────


def test_concurrent_access_safe(cache):
    errors: list[Exception] = []

    def rw(i):
        try:
            for _ in range(30):
                cache.set_price(f"T{i}", {"last": i})
                assert cache.get_price(f"T{i}")["last"] == i
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=rw, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors


# ── LC-2.1.15 auto-creates parent directory ──────────────────────────────────


def test_parent_dir_auto_created(tmp_path):
    target = tmp_path / "nested" / "deeper" / "cache.db"
    assert not target.exists()
    LocalCache(str(target))
    assert target.exists()


# ── LH-2.2.1 hit rate ─────────────────────────────────────────────────────────


def test_hit_rate_ninety_percent_on_repeat_reads(cache):
    cache.set_price("AAPL", {"last": 150})
    for _ in range(10):
        cache.get_price("AAPL")
    # one missing plus ten hits
    cache.get_price("MISSING")
    stats = cache.stats()
    assert stats["hits"] == 10
    assert stats["misses"] == 1
    assert stats["hit_rate"] > 0.9


# ── Extras: delete + clear ───────────────────────────────────────────────────


def test_delete(cache):
    cache.set_price("AAPL", {"last": 150})
    assert cache.delete("price_quote", "AAPL") is True
    assert cache.get_price("AAPL") is None


def test_clear(cache):
    cache.set_price("AAPL", {"last": 150})
    cache.set_news("AAPL", [{}])
    cache.clear()
    assert cache.get_price("AAPL") is None
    assert cache.get_news("AAPL") is None


def test_bars_category_auto_selected(cache):
    cache.set_bars("AAPL", "1mo", "1d", {"d": 1})
    cache.set_bars("AAPL", "1d", "5m", {"m": 1})
    assert cache.get_bars("AAPL", "1mo", "1d") == {"d": 1}
    assert cache.get_bars("AAPL", "1d", "5m") == {"m": 1}
