"""DataRouter tests — DR-3.1.* from test plan.

Uses fake providers to assert routing decisions without hitting network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_trading_system.data.data_router import DataRouter
from stock_trading_system.data.local_cache import LocalCache


class FakeQwen:
    """Minimal QwenProvider stand-in."""
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.get_stock_price = MagicMock(return_value=None)
        self.get_fundamentals = MagicMock(return_value=None)
        self.get_news = MagicMock(return_value=[])
        self.screen_stocks = MagicMock(return_value=[])


class FakeYFinance:
    def __init__(self):
        self.get_stock_price = MagicMock(return_value=None)
        self.get_fundamentals = MagicMock(return_value=None)
        self.get_news = MagicMock(return_value=[])
        self.get_stock_history = MagicMock(return_value=None)


class FakeAkShare:
    def __init__(self):
        self.get_stock_price = MagicMock(return_value=None)
        self.get_fundamentals = MagicMock(return_value=None)
        self.get_news = MagicMock(return_value=[])
        self.get_stock_history = MagicMock(return_value=None)


class FakeSchwab:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.get_stock_price = MagicMock(return_value=None)
        self.get_stock_history = MagicMock(return_value=None)
        self.token_age_days = MagicMock(return_value=None)


def _router(config, cache=None, **overrides):
    return DataRouter(
        config,
        qwen=overrides.get("qwen", FakeQwen()),
        yfinance=overrides.get("yfinance", FakeYFinance()),
        akshare=overrides.get("akshare", FakeAkShare()),
        schwab=overrides.get("schwab", FakeSchwab()),
        cache=cache,
    )


@pytest.fixture
def cache(tmp_path):
    return LocalCache(str(tmp_path / "cache.db"))


def _cfg(primary="qwen"):
    return {"data_routing": {"primary": primary, "enable_cache": True}}


# ── DR-3.1.1 primary=qwen routes through Qwen first ──────────────────────────


def test_primary_qwen_calls_qwen_first(cache):
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 150.0}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen)
    result = r.get_price("AAPL")
    assert result["last"] == 150.0
    qwen.get_stock_price.assert_called_once_with("AAPL")


# ── DR-3.1.2 Qwen miss falls back ────────────────────────────────────────────


def test_qwen_miss_falls_back_to_yfinance(cache):
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = None
    yf = FakeYFinance()
    yf.get_stock_price.return_value = {"last": 148.5}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    result = r.get_price("AAPL")
    assert result["last"] == 148.5
    yf.get_stock_price.assert_called_once()


# ── DR-3.1.3 primary=local bypasses Qwen ─────────────────────────────────────


def test_primary_local_skips_qwen(cache):
    qwen = FakeQwen()
    yf = FakeYFinance()
    yf.get_stock_price.return_value = {"last": 148.5}
    r = _router(_cfg("local"), cache=cache, qwen=qwen, yfinance=yf)
    result = r.get_price("AAPL")
    assert result["last"] == 148.5
    qwen.get_stock_price.assert_not_called()


# ── DR-3.1.4 A-share routes to AkShare when primary=local ────────────────────


def test_cn_ticker_routes_to_akshare_when_local(cache):
    ak = FakeAkShare()
    ak.get_stock_price.return_value = {"last": 1500.0}
    r = _router(_cfg("local"), cache=cache, akshare=ak)
    result = r.get_price("600519")
    assert result["last"] == 1500.0
    ak.get_stock_price.assert_called_once()


def test_cn_ticker_routes_to_qwen_when_primary_qwen(cache):
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 1500.0}
    ak = FakeAkShare()
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, akshare=ak)
    result = r.get_price("600519")
    assert result["last"] == 1500.0
    qwen.get_stock_price.assert_called_once()
    ak.get_stock_price.assert_not_called()


# ── DR-3.1.5 cache hit skips external calls ──────────────────────────────────


def test_cache_hit_skips_external(cache):
    cache.set_price("AAPL", {"last": 150.0})
    qwen = FakeQwen()
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen)
    result = r.get_price("AAPL")
    assert result["last"] == 150.0
    qwen.get_stock_price.assert_not_called()


# ── DR-3.1.6 cache miss triggers external + writes back ──────────────────────


def test_cache_miss_writes_back(cache):
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 150.0}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen)
    r.get_price("AAPL")
    # Next call must be a cache hit
    r.get_price("AAPL")
    assert qwen.get_stock_price.call_count == 1


# ── DR-3.1.7 enable_cache=false skips cache ──────────────────────────────────


def test_cache_disabled_always_calls_source(tmp_path):
    cfg = {"data_routing": {"primary": "qwen", "enable_cache": False}}
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 150.0}
    cache = LocalCache(str(tmp_path / "cache.db"))
    r = _router(cfg, cache=cache, qwen=qwen)
    r.get_price("AAPL")
    r.get_price("AAPL")
    assert qwen.get_stock_price.call_count == 2


# ── DR-3.1.8 get_history_for_backtest NEVER hits Qwen ────────────────────────


def test_backtest_history_never_routes_qwen(cache):
    qwen = FakeQwen()
    yf = FakeYFinance()
    yf.get_stock_history.return_value = pd.DataFrame({
        "open": [1, 2, 3], "high": [1.1, 2.1, 3.1],
        "low": [0.9, 1.9, 2.9], "close": [1.05, 2.05, 3.05],
        "volume": [100, 200, 300],
    }, index=pd.date_range("2026-01-01", periods=3, freq="D"))
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    df = r.get_history_for_backtest("AAPL", period="1mo", interval="1d")
    assert df is not None and len(df) == 3
    # Qwen must not be involved
    qwen.get_stock_price.assert_not_called()
    qwen.get_fundamentals.assert_not_called()


# ── DR-3.1.9 history cache hit ───────────────────────────────────────────────


def test_backtest_history_cache_hit(cache):
    yf = FakeYFinance()
    df1 = pd.DataFrame({"close": [1, 2, 3]},
                       index=pd.date_range("2026-01-01", periods=3, freq="D"))
    yf.get_stock_history.return_value = df1
    r = _router(_cfg("qwen"), cache=cache, yfinance=yf)
    r.get_history_for_backtest("AAPL", "1mo", "1d")
    r.get_history_for_backtest("AAPL", "1mo", "1d")
    # Only one actual fetch; second served from cache.
    assert yf.get_stock_history.call_count == 1


# ── DR-3.1.10 Qwen disabled → fall through to yfinance ───────────────────────


def test_qwen_disabled_routes_local(cache):
    qwen = FakeQwen(enabled=False)
    yf = FakeYFinance()
    yf.get_stock_price.return_value = {"last": 148.5}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    result = r.get_price("AAPL")
    assert result["last"] == 148.5
    qwen.get_stock_price.assert_not_called()


# ── DR-3.1.11 providers.yfinance_enabled=false disables yfinance ─────────────


def test_providers_disabled_skips_them(cache):
    cfg = {
        "data_routing": {"primary": "qwen", "enable_cache": True},
        "providers": {"yfinance_enabled": False, "akshare_enabled": False},
    }
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = None  # Qwen also fails
    yf = FakeYFinance()
    yf.get_stock_price.return_value = {"last": 148.5}  # would be used if enabled
    r = DataRouter(cfg, qwen=qwen, yfinance=yf, akshare=FakeAkShare(), cache=cache)
    result = r.get_price("AAPL")
    assert result is None  # all sources disabled or failed
    yf.get_stock_price.assert_not_called()


# ── Fundamentals routing ─────────────────────────────────────────────────────


def test_fundamentals_qwen_primary(cache):
    qwen = FakeQwen()
    qwen.get_fundamentals.return_value = {
        "ticker": "AAPL", "pe_ratio": 28.5, "pb_ratio": 45.0,
        "roe": 147, "eps": 6.5, "market_cap": 3e12,
    }
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen)
    result = r.get_fundamentals("AAPL")
    assert result is not None
    assert result["pe_ratio"] == 28.5


def test_fundamentals_invalid_data_falls_back(cache):
    """Qwen returns data but it's too sparse → validator rejects → fallback."""
    qwen = FakeQwen()
    qwen.get_fundamentals.return_value = {"ticker": "AAPL", "pe_ratio": 20}  # too sparse
    yf = FakeYFinance()
    yf.get_fundamentals.return_value = {
        "ticker": "AAPL", "pe_ratio": 28.5,  # yfinance returns raw dict
        "marketCap": 3e12,
    }
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    result = r.get_fundamentals("AAPL")
    # Validator rejects Qwen's sparse record; yfinance raw dict returned as-is
    assert result is not None
    yf.get_fundamentals.assert_called_once()


# ── News routing ─────────────────────────────────────────────────────────────


def test_news_qwen_primary(cache):
    qwen = FakeQwen()
    qwen.get_news.return_value = [
        {"title": "Apple news", "url": "https://yahoo.com/a", "date": "2026-04-14",
         "source": "Yahoo", "summary": "AAPL up 2%"}
    ]
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen)
    news = r.get_news("AAPL")
    assert len(news) == 1
    assert news[0]["title"] == "Apple news"


def test_news_qwen_empty_falls_back(cache):
    qwen = FakeQwen()
    qwen.get_news.return_value = []
    yf = FakeYFinance()
    yf.get_news.return_value = [
        {"title": "Fallback news", "url": "https://yf.com/n", "date": "2026-04-14"}
    ]
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    news = r.get_news("AAPL")
    assert len(news) == 1
    assert news[0]["title"] == "Fallback news"


# ── Empty ticker / edge cases ────────────────────────────────────────────────


def test_empty_ticker_returns_none_or_empty(cache):
    r = _router(_cfg("qwen"), cache=cache)
    assert r.get_price("") is None
    assert r.get_fundamentals("") is None
    assert r.get_news("") == []
    assert r.get_history_for_backtest("") is None


def test_routing_summary(cache):
    r = _router(_cfg("qwen"), cache=cache)
    s = r.routing_summary()
    assert s["primary"] == "qwen"
    assert s["cache_enabled"] is True


# ── Quote validator rejects garbage prices before caching ────────────────────


def test_bad_price_from_qwen_falls_through(cache):
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 0}  # invalid
    yf = FakeYFinance()
    yf.get_stock_price.return_value = {"last": 150.0}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, yfinance=yf)
    result = r.get_price("AAPL")
    assert result["last"] == 150.0


# ── DR-3.1.12 Schwab realtime primary takes precedence ──────────────────


def test_schwab_realtime_primary_runs_first(cache):
    schwab = FakeSchwab(enabled=True)
    schwab.get_stock_price.return_value = {"last": 175.0}
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 150.0}
    cfg = {
        "data_routing": {
            "primary": "qwen", "realtime_primary": "schwab",
            "enable_cache": True,
        },
    }
    r = _router(cfg, cache=cache, qwen=qwen, schwab=schwab)
    result = r.get_price("AAPL")
    assert result["last"] == 175.0
    schwab.get_stock_price.assert_called_once_with("AAPL")
    qwen.get_stock_price.assert_not_called()


def test_schwab_disabled_falls_through_to_qwen(cache):
    """Schwab provider disabled (no token) → use Qwen primary."""
    schwab = FakeSchwab(enabled=False)
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 150.0}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, schwab=schwab)
    result = r.get_price("AAPL")
    assert result["last"] == 150.0
    schwab.get_stock_price.assert_not_called()
    qwen.get_stock_price.assert_called_once()


def test_schwab_skipped_for_cn_ticker(cache):
    schwab = FakeSchwab(enabled=True)
    schwab.get_stock_price.return_value = {"last": 999}  # never used for CN
    qwen = FakeQwen()
    qwen.get_stock_price.return_value = {"last": 1500.0}
    r = _router(_cfg("qwen"), cache=cache, qwen=qwen, schwab=schwab)
    result = r.get_price("600519")
    assert result["last"] == 1500.0
    schwab.get_stock_price.assert_not_called()


def test_routing_summary_includes_schwab(cache):
    schwab = FakeSchwab(enabled=True)
    schwab.token_age_days.return_value = 0.5
    r = _router(_cfg("qwen"), cache=cache, schwab=schwab)
    s = r.routing_summary()
    assert s["realtime_primary"] == "schwab"
    assert s["schwab_enabled"] is True
    assert s["schwab_token_age_days"] == 0.5
