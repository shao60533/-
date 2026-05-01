"""Real-data fetchers feed the v1.19.1 News + Fundamentals tabs."""

from __future__ import annotations

from stock_trading_system.agents.rendering.data_sources import (
    fetch_fundamentals_facts,
    fetch_news_headlines,
)


class _StubDM:
    def __init__(self, *, info=None, news=None, raise_=None):
        self._info = info
        self._news = news
        self._raise = raise_

    def get_fundamentals(self, ticker):  # noqa: ARG002 - DataManager shape
        if self._raise:
            raise RuntimeError(self._raise)
        return self._info

    def get_news(self, ticker):  # noqa: ARG002 - DataManager shape
        if self._raise:
            raise RuntimeError(self._raise)
        return self._news


# ── Fundamentals ─────────────────────────────────────────────────────────

def test_fundamentals_maps_yfinance_info():
    info = {
        "trailingPE": 28.5, "priceToBook": 6.1,
        "priceToSalesTrailing12Months": 7.2,
        "enterpriseToEbitda": 21.0,
        "pegRatio": 1.8,
        "returnOnEquity": 0.31,            # decimal → 31.0 percent
        "returnOnAssets": 0.21,
        "debtToEquity": 105.0,
        "currentRatio": 1.4,
        "quickRatio": 0.9,
        "revenueGrowth": 0.18,             # decimal → 18.0 percent
        "earningsGrowth": 0.25,
        "freeCashflowGrowth": 0.12,
        "grossMargins": 0.45,
        "operatingMargins": 0.32,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "marketCap": 3_000_000_000_000,
    }
    out = fetch_fundamentals_facts("AAPL", _StubDM(info=info))
    # Valuation block: floats kept as-is.
    assert out["valuation"]["pe"] == 28.5
    assert out["valuation"]["pb"] == 6.1
    assert out["valuation"]["peg"] == 1.8
    # Growth + profitability blocks: 0..1 ratios upcast to percents.
    assert out["growth"]["revenue_yoy_pct"] == 18.0
    assert out["growth"]["eps_yoy_pct"] == 25.0
    assert out["profitability"]["roe_pct"] == 31.0
    assert out["profitability"]["op_margin_pct"] == 32.0
    # Balance sheet kept raw (yfinance ratios already in real units).
    assert out["balance_sheet"]["debt_to_equity"] == 105.0
    # Provider metadata surfaced for downstream uses.
    assert out["sector"] == "Technology"
    assert out["market_cap"] == 3_000_000_000_000


def test_fundamentals_handles_missing_fields():
    out = fetch_fundamentals_facts("XYZ", _StubDM(info={}))
    assert out["valuation"]["pe"] is None
    assert out["growth"]["revenue_yoy_pct"] is None
    assert out["balance_sheet"]["current_ratio"] is None


def test_fundamentals_swallow_provider_error():
    """Provider exceptions ⇒ empty dict so the extractor falls back to LLM."""
    out = fetch_fundamentals_facts("XYZ", _StubDM(raise_="boom"))
    assert out == {}


def test_fundamentals_handles_none_info():
    """When the provider returns None, treat it like an empty dict — every
    numeric field is ``None`` but the four blocks are still present so the
    extractor and the UI can shape-check without ``KeyError``."""
    out = fetch_fundamentals_facts("XYZ", _StubDM(info=None))
    assert out["valuation"]["pe"] is None
    assert out["growth"]["revenue_yoy_pct"] is None
    assert out["sector"] is None


def test_fundamentals_data_manager_none():
    assert fetch_fundamentals_facts("XYZ", None) == {}


# ── News ─────────────────────────────────────────────────────────────────

def test_news_normalizes_dates_and_caps():
    items = [
        # epoch seconds — UTC 2024-04-30 00:00
        {"title": "T1", "source": "Reuters", "published": "1714435200"},
        # ISO with timezone — first 10 chars are the date.
        {"title": "T2", "published": "2026-04-30T10:00:00Z"},
        # Bare YYYY-MM-DD
        {"title": "T3", "date": "2026-04-29"},
    ]
    out = fetch_news_headlines("X", _StubDM(news=items), limit=5)
    assert [h["title"] for h in out] == ["T1", "T2", "T3"]
    assert out[0]["date"] == "2024-04-30"
    assert out[1]["date"] == "2026-04-30"
    assert out[2]["date"] == "2026-04-29"
    # Default labels — sentiment / impact get filled later by the LLM.
    assert all(h["sentiment"] == "neutral" for h in out)
    assert all(h["impact"] == "medium" for h in out)


def test_news_skips_titleless_and_caps_at_limit():
    items = [{"title": ""}, {"title": "real"}, {"foo": "bar"}]
    out = fetch_news_headlines("X", _StubDM(news=items), limit=8)
    assert [h["title"] for h in out] == ["real"]


def test_news_swallow_provider_error():
    out = fetch_news_headlines("X", _StubDM(raise_="boom"))
    assert out == []


def test_news_handles_invalid_date_safely():
    items = [{"title": "T", "published": "not-a-date"}]
    out = fetch_news_headlines("X", _StubDM(news=items))
    assert out[0]["date"] is None


def test_news_data_manager_none():
    assert fetch_news_headlines("X", None) == []
