"""v1.2 fix verification: batch_analysis children are first-class in /api/history.

Spec §12 point 9 demands that the new analysis_history rows minted by
record_child_analysis surface through /api/history?include_running=true
exactly like the single-ticker rows. This test wires the real Flask app
+ TaskManager + real sqlite store and stubs only the LLM-bound analyzer
so we never make a network call.

Why this lives in tests/web/ (not tests/tasks/): the assertion is on
the HTTP envelope, not the worker plumbing. tests/tasks/
test_batch_analysis_history_split.py already covers the DB-level
invariants — this one is the API-visibility regression guard.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from stock_trading_system.web import app as app_module


def _stub_analyze(ticker, date=None, **kwargs):
    """Deterministic analyzer stub — never touches the network."""
    return SimpleNamespace(
        signal="BUY",
        market_report=f"{ticker} market",
        sentiment_report=f"{ticker} sentiment",
        news_report=f"{ticker} news",
        fundamentals_report=f"{ticker} fundamentals",
        investment_debate={"bull": "ok"},
        risk_assessment={"risk": "low"},
        trade_decision={"action": "BUY"},
    )


def _add_holding(client, ticker: str, shares: float, price: float) -> None:
    resp = client.post(
        "/api/portfolio/add",
        json={"ticker": ticker, "shares": shares, "price": price},
    )
    assert resp.status_code == 200, resp.get_json()


def test_batch_children_show_up_in_api_history(alice_client, app_client):
    """alice → batch_analyze 2 holdings → /api/history returns 2 rows.

    Each row points at a synthetic ``batch:{parent}:{ticker}:{idx}``
    task_id (proving it came from the v1.2 fan-out path, not a
    stale single-ticker submission), and each is openable via
    /api/history/<analysis_id>.
    """
    _add_holding(alice_client, "AAPL", 10, 150.0)
    _add_holding(alice_client, "MSFT", 5, 320.0)

    # Replace analyzer.analyze with the stub. The analyzer singleton is
    # built lazily; touch _get_analyzer() to mint it so we can monkey
    # the .analyze method before the batch worker calls it.
    analyzer = app_module._get_analyzer()
    with patch.object(analyzer, "analyze", side_effect=_stub_analyze):
        resp = alice_client.post(
            "/api/batch/analyze",
            json={"skip_recent_hours": 0},
        )
        assert resp.status_code == 200, resp.get_json()
        task_id = resp.get_json()["task_id"]

        # Block on completion. Real-fast with the stub (no LLM).
        tm = app_module._task_manager
        assert tm is not None
        final = tm.wait_for(task_id, timeout=30)
        assert final["status"] == "success", final

    # /api/history?include_running=true returns the inbox shape:
    # mix of running tasks + completed analysis rows.
    resp = alice_client.get("/api/history?include_running=true&limit=50")
    assert resp.status_code == 200
    body = resp.get_json()
    analyses = [it for it in body["items"] if it.get("kind") == "analysis"]
    by_ticker = {it["ticker"]: it for it in analyses}

    # Both AAPL and MSFT must be present as first-class analysis rows.
    assert "AAPL" in by_ticker, [it["ticker"] for it in analyses]
    assert "MSFT" in by_ticker, [it["ticker"] for it in analyses]

    # The task_id stamped on each row is the synthetic child id, not
    # the parent batch task id. This proves the fan-out path ran (vs
    # the v1.0 generic-blob path where no analysis_history rows
    # would exist at all).
    for ticker in ("AAPL", "MSFT"):
        row = by_ticker[ticker]
        assert isinstance(row["id"], int)
        assert row["id"] > 0
        assert row["task_id"].startswith(f"batch:{task_id}:"), row
        assert ticker in row["task_id"]

    # Each child must be openable via /api/history/<id> with a full
    # structured payload — spec §12 point 9.
    for ticker in ("AAPL", "MSFT"):
        detail = alice_client.get(f"/api/history/{by_ticker[ticker]['id']}")
        assert detail.status_code == 200, detail.get_json()
        d = detail.get_json()
        assert d["ticker"] == ticker
        assert d["signal"] == "BUY"
        # Reports made it into the row, not just the signal headline.
        assert ticker in (d.get("market_report") or "")
