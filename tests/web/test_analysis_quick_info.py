"""/api/analysis/<id>/quick-info aggregates news + fundamentals.

Bug pre-v1.16: AnalysisDetailView fired two parallel XHRs (/api/news/X
and /api/fundamentals/X) to fill the quick-info card on every detail
mount. Aggregating into one round-trip halves request count and lets
the backend short-circuit failures gracefully.
"""

from __future__ import annotations

from unittest.mock import patch

from stock_trading_system.portfolio.database import PortfolioDatabase


def _seed(app_client, ticker="AAPL") -> int:
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id,
    })


def test_quick_info_returns_aggregated_payload(alice_client, app_client):
    aid = _seed(app_client)
    fake_news = [{"title": "AAPL +5%", "source": "Reuters"}]
    fake_fund = {"pe": 28.5, "market_cap": 3.5e12}
    with patch.object(
        _lazy_dm(), "get_news", return_value=fake_news,
    ), patch.object(
        _lazy_dm(), "get_fundamentals", return_value=fake_fund,
    ):
        body = alice_client.get(f"/api/analysis/{aid}/quick-info").get_json()
    assert body["ticker"] == "AAPL"
    assert body["news"] == fake_news
    assert body["fundamentals"] == fake_fund


def test_quick_info_404_for_missing_analysis(alice_client):
    resp = alice_client.get("/api/analysis/9999999/quick-info")
    assert resp.status_code == 404


def test_quick_info_partial_failure_degrades_gracefully(
    alice_client, app_client,
):
    """News provider down → returns empty list, fundamentals still
    flows through. Should never 500 the whole quick-info call."""
    aid = _seed(app_client)
    with patch.object(
        _lazy_dm(), "get_news", side_effect=RuntimeError("provider down"),
    ), patch.object(
        _lazy_dm(), "get_fundamentals", return_value={"pe": 30.0},
    ):
        resp = alice_client.get(f"/api/analysis/{aid}/quick-info")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["news"] == []
    assert body["fundamentals"] == {"pe": 30.0}


def test_quick_info_caps_news_at_three(alice_client, app_client):
    aid = _seed(app_client)
    many = [{"title": f"n{i}"} for i in range(10)]
    with patch.object(
        _lazy_dm(), "get_news", return_value=many,
    ), patch.object(
        _lazy_dm(), "get_fundamentals", return_value=None,
    ):
        body = alice_client.get(f"/api/analysis/{aid}/quick-info").get_json()
    assert len(body["news"]) == 3


def _lazy_dm():
    """Resolve the singleton DataManager class so test patches target the
    right symbol regardless of which module path imports it."""
    from stock_trading_system.data.data_manager import DataManager
    return DataManager
