"""Qwen extension tests — QF-4.1.*, QN-4.2.*, DV-3.2.*

We mock QwenProvider._call to return canned LLM-shaped responses so these
tests run without network access or API keys.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from stock_trading_system.data.qwen_provider import QwenProvider
from stock_trading_system.data.validators import (
    validate_fundamentals, validate_news, validate_quote,
)


def _enabled_config():
    return {"qwen": {"enabled": True, "api_key": "fake", "model": "qwen-plus"}}


# ── QF-4.1.1 US fundamentals happy path ──────────────────────────────────────


def test_get_fundamentals_us_complete():
    canned = {
        "ticker": "AAPL", "market_cap": 3.2e12,
        "pe_ratio": 28.5, "pb_ratio": 45.0, "roe": 147.2,
        "gross_margin": 43.1, "net_margin": 25.3, "revenue_growth": 8.1,
        "dividend_yield": 0.6, "beta": 1.2,
        "week_52_high": 237.23, "week_52_low": 164.08, "eps": 6.5,
        "confidence": "high", "as_of": "2026-04-14",
        "source": "https://finance.yahoo.com/quote/AAPL",
    }
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        result = qp.get_fundamentals("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["pe_ratio"] == 28.5
    assert result["roe"] == 147.2
    assert result["confidence"] == "high"
    assert result["source"].startswith("qwen:")


# ── QF-4.1.2 A-share fundamentals ────────────────────────────────────────────


def test_get_fundamentals_a_share():
    canned = {
        "ticker": "600519", "market_cap": 1.9e12, "pe_ratio": 22.3,
        "pb_ratio": 7.8, "roe": 32.1, "net_margin": 52.0,
        "revenue_growth": 15.6,
    }
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        result = qp.get_fundamentals("600519")
    assert result["ticker"] == "600519"
    assert result["pe_ratio"] == 22.3


# ── QF-4.1.3 invalid ticker returns None ─────────────────────────────────────


def test_get_fundamentals_error_response_returns_none():
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value={"error": "Ticker not found"}):
        assert qp.get_fundamentals("ZZZZ") is None


def test_get_fundamentals_empty_ticker_returns_none():
    qp = QwenProvider(_enabled_config())
    assert qp.get_fundamentals("") is None
    assert qp.get_fundamentals("   ") is None


# ── QF-4.1.4 source + as_of preserved ────────────────────────────────────────


def test_get_fundamentals_source_as_of_preserved():
    qp = QwenProvider(_enabled_config())
    canned = {"ticker": "AAPL", "pe_ratio": 20, "pb_ratio": 40, "eps": 5,
              "as_of": "2026-04-14", "source": "yahoo"}
    with patch.object(qp, "_call", return_value=canned):
        result = qp.get_fundamentals("AAPL")
    assert result["as_of"] == "2026-04-14"
    assert result["source"] == "qwen:yahoo"


# ── QF-4.1.8 disabled provider ───────────────────────────────────────────────


def test_get_fundamentals_disabled_provider():
    qp = QwenProvider({"qwen": {"enabled": False}})
    assert qp.get_fundamentals("AAPL") is None


# ── QF-4.1.7 numeric coercion for string numbers ─────────────────────────────


def test_get_fundamentals_accepts_string_numbers():
    qp = QwenProvider(_enabled_config())
    canned = {
        "ticker": "AAPL", "pe_ratio": "28.5", "pb_ratio": "45",
        "roe": "147.2%", "market_cap": "3,200,000,000,000", "eps": "6.5",
    }
    with patch.object(qp, "_call", return_value=canned):
        result = qp.get_fundamentals("AAPL")
    assert result["pe_ratio"] == 28.5
    assert result["market_cap"] == 3.2e12
    assert result["roe"] == 147.2


# ── QN-4.2.1 news happy path ─────────────────────────────────────────────────


def test_get_news_basic():
    canned = {"news": [
        {"title": "Apple hits new high",
         "url": "https://finance.yahoo.com/news/apple",
         "date": "2026-04-14", "source": "Yahoo",
         "summary": "AAPL closed up 2%"},
        {"title": "Analyst upgrades AAPL",
         "url": "https://bloomberg.com/news/aapl",
         "date": "2026-04-13", "source": "Bloomberg",
         "summary": "Price target raised"},
    ]}
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        news = qp.get_news("AAPL")
    assert len(news) == 2
    assert news[0]["title"] == "Apple hits new high"
    assert all(n["url"].startswith("http") for n in news)


# ── QN-4.2.2 limit enforced ──────────────────────────────────────────────────


def test_get_news_respects_limit():
    canned = {"news": [
        {"title": f"News {i}", "url": f"https://x.com/{i}"}
        for i in range(10)
    ]}
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        news = qp.get_news("AAPL", limit=3)
    assert len(news) == 3


# ── QN-4.2.3 Chinese news (A-share) ──────────────────────────────────────────


def test_get_news_chinese_locale():
    canned = {"news": [
        {"title": "贵州茅台Q1营收超预期",
         "url": "https://finance.sina.com.cn/roll/600519.html",
         "date": "2026-04-14", "source": "新浪财经",
         "summary": "茅台财报数据亮眼"},
    ]}
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        news = qp.get_news("600519")
    assert news[0]["source"] == "新浪财经"
    assert "茅台" in news[0]["title"]


# ── QN-4.2.5 empty + QN-4.2.6 url filter ─────────────────────────────────────


def test_get_news_empty_result():
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value={"news": []}):
        assert qp.get_news("AAPL") == []
    with patch.object(qp, "_call", return_value=None):
        assert qp.get_news("AAPL") == []


def test_get_news_filters_bad_urls():
    canned = {"news": [
        {"title": "Good", "url": "https://real.com/a"},
        {"title": "Bad", "url": "not-a-url"},
        {"title": "No URL"},
        {"title": "Empty", "url": ""},
    ]}
    qp = QwenProvider(_enabled_config())
    with patch.object(qp, "_call", return_value=canned):
        news = qp.get_news("AAPL")
    assert len(news) == 1
    assert news[0]["title"] == "Good"


def test_get_news_disabled_provider():
    qp = QwenProvider({"qwen": {"enabled": False}})
    assert qp.get_news("AAPL") == []


# ── QH-4.3.1 no get_history method ───────────────────────────────────────────


def test_qwen_does_not_expose_get_history():
    qp = QwenProvider(_enabled_config())
    assert not hasattr(qp, "get_history"), \
        "QwenProvider must not expose a get_history method — historical " \
        "OHLCV is delegated to yfinance/AkShare per architecture proposal §4.4.3"


# ══════════════════════════════════════════════════════════════════════════
# Validators (DV-3.2.*)
# ══════════════════════════════════════════════════════════════════════════


def test_validate_fundamentals_passes_reasonable_record():
    ok = {
        "ticker": "AAPL", "market_cap": 3e12, "pe_ratio": 28.5,
        "pb_ratio": 40, "roe": 147, "eps": 6.5,
    }
    result = validate_fundamentals(ok)
    assert result is not None
    assert result["pe_ratio"] == 28.5


# ── DV-3.2.1 PE extreme value filtered ───────────────────────────────────────


def test_validate_drops_insane_pe():
    bad = {
        "ticker": "AAPL", "pe_ratio": 999_999, "market_cap": 3e12,
        "pb_ratio": 40, "eps": 6.5,
    }
    result = validate_fundamentals(bad)
    assert result is not None
    assert result["pe_ratio"] is None
    assert "pe_ratio" in result["validation_warnings"]


# ── DV-3.2.2 negative market cap filtered ────────────────────────────────────


def test_validate_drops_negative_market_cap():
    bad = {
        "ticker": "AAPL", "market_cap": -1e9, "pe_ratio": 20,
        "pb_ratio": 5, "eps": 3,
    }
    result = validate_fundamentals(bad)
    assert result["market_cap"] is None


# ── DV-3.2.3 ROE out of range ────────────────────────────────────────────────


def test_validate_drops_extreme_roe():
    bad = {
        "ticker": "AAPL", "roe": 1500, "pe_ratio": 20, "pb_ratio": 5, "eps": 3,
    }
    result = validate_fundamentals(bad)
    assert result["roe"] is None


# ── DV-3.2.4 empty ticker ────────────────────────────────────────────────────


def test_validate_rejects_empty_ticker():
    assert validate_fundamentals({"ticker": "", "pe_ratio": 20}) is None
    assert validate_fundamentals({}) is None
    assert validate_fundamentals(None) is None


# ── DV-3.2.5 too few fields ──────────────────────────────────────────────────


def test_validate_rejects_too_sparse_record():
    # Only ticker + 1 number — not informative enough
    assert validate_fundamentals({"ticker": "AAPL", "pe_ratio": 20}) is None


# ── DV-3.2.6 None input (simulating JSON parse failure) ──────────────────────


def test_validate_handles_none():
    assert validate_fundamentals(None) is None


# ── News validator ───────────────────────────────────────────────────────────


def test_validate_news_drops_bad_items():
    raw = [
        {"title": "Ok", "url": "https://a.com"},
        {"title": "", "url": "https://b.com"},   # empty title
        {"title": "Bad URL", "url": "ftp://x"},  # non-http
        {"title": "Missing URL"},
        None,                                     # non-dict
    ]
    cleaned = validate_news(raw)
    assert len(cleaned) == 1
    assert cleaned[0]["title"] == "Ok"


def test_validate_news_empty_input():
    assert validate_news([]) == []
    assert validate_news(None) == []


# ── Quote validator ──────────────────────────────────────────────────────────


def test_validate_quote_rejects_zero_and_negative():
    assert validate_quote(None) is None
    assert validate_quote({}) is None
    assert validate_quote({"last": 0}) is None
    assert validate_quote({"last": -5}) is None
    assert validate_quote({"last": 1e9}) is None  # absurdly high
    assert validate_quote({"last": 150.0}) == {"last": 150.0}
    # Falls back to "close" when "last" missing
    assert validate_quote({"close": 100}) == {"close": 100}
