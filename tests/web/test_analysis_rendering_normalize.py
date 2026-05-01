"""Backend rendering normalization keeps the React detail page from
white-screening on malformed structured-card payloads.

Production /analysis/17 (SNDK) returned a ``rendering`` blob whose
``Market.support_resistance[i].price`` was a string, which crashed the
React ``support_resistance.sort + price.toFixed`` chain and unmounted
the entire React root. We now defensively normalise on the server
side AND wrap each tab card in an ErrorBoundary on the client.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.web.app import _parse_rendering


# ── _parse_rendering unit tests ──────────────────────────────────────────


def test_parse_rendering_handles_none():
    assert _parse_rendering(None) == {}


def test_parse_rendering_handles_invalid_json():
    assert _parse_rendering("not json") == {}


def test_parse_rendering_drops_non_dict_card():
    raw = json.dumps({"summary": "string-not-dict", "Market": {"trend": "bullish"}})
    out = _parse_rendering(raw)
    assert "summary" not in out
    assert out["Market"]["trend"] == "bullish"


def test_market_card_normalises_non_finite_price():
    """Production SNDK shape — string price + non-list patterns."""
    raw = json.dumps({"Market": {
        "trend": "bearish",
        "support_resistance": [
            {"price": 32.50, "kind": "support"},
            {"price": "—", "kind": "resistance"},  # crashed the old client
            {"price": "$45.30", "kind": "resistance"},  # also bad
        ],
        "patterns": "rising-wedge",  # should be a list, but isn't
        "indicators": None,
    }})
    out = _parse_rendering(raw)["Market"]
    prices = [lvl["price"] for lvl in out["support_resistance"]]
    assert prices[0] == 32.50
    assert prices[1] is None
    assert prices[2] is None
    assert out["patterns"] == []
    assert out["indicators"] == []


def test_decision_card_strips_non_finite_numbers():
    raw = json.dumps({"Decision": {
        "final_action": "SELL",
        "conviction": "high",
        "time_horizon": "short",
        "entry_zone": {"low": "—", "high": 32.0},
        "structural_stop": "n/a",
        "take_profit_levels": [
            {"price": "30", "weight_pct": 50},
            {"price": "bad", "weight_pct": "x"},
        ],
        "preconditions": ["volume confirms"],
        "exit_conditions": None,
        "alternative_scenarios": "table-not-array",
        "one_line_summary": "Sell on rallies",
    }})
    out = _parse_rendering(raw)["Decision"]
    # entry_zone object preserved but the bad ``low`` is left as-is
    # (front-end coerces again via toFiniteNumber); structural_stop
    # is normalised on the server.
    assert out["structural_stop"] is None
    assert out["preconditions"] == ["volume confirms"]
    assert out["exit_conditions"] == []
    assert out["alternative_scenarios"] == []


def test_overview_card_handles_partial_debate_synthesis():
    raw = json.dumps({"summary": {
        "rating": "Sell",
        "confidence": "high",
        "action_direction": "Trim into strength",
        "debate_synthesis": "string-not-dict",   # malformed
        "decision_drivers": "should-be-list",     # malformed
        "key_metrics": None,
        "one_line_takeaway": "Pricing pressure tips the balance.",
    }})
    out = _parse_rendering(raw)["summary"]
    assert out["debate_synthesis"] is None
    assert out["decision_drivers"] == []
    assert out["key_metrics"] == []


def test_risk_card_stance_dropped_when_invalid():
    raw = json.dumps({"Risk Assessment": {
        "aggressive": "string-not-dict",
        "conservative": {"claim": "ok", "evidence": "ok", "limitation": "ok"},
        "neutral": None,
        "verdict": "moderate",
        "top_risks": None,
    }})
    out = _parse_rendering(raw)["Risk Assessment"]
    assert out["aggressive"] is None
    assert out["neutral"] is None
    assert isinstance(out["conservative"], dict)
    assert out["top_risks"] == []


def test_news_card_array_coercion():
    raw = json.dumps({"News": {
        "summary": "summary text",
        "headlines": "not a list",
        "catalysts": None,
    }})
    out = _parse_rendering(raw)["News"]
    assert out["headlines"] == []
    assert out["catalysts"] == []


def test_fundamentals_card_drops_invalid_quality_score():
    raw = json.dumps({"Fundamentals": {
        "summary": "ok",
        "valuation": "string-not-dict",
        "growth": None,
        "profitability": {"roe_pct": 12.3},
        "balance_sheet": "x",
        "quality_score": "n/a",
    }})
    out = _parse_rendering(raw)["Fundamentals"]
    assert out["valuation"] is None
    assert out["growth"] is None
    assert out["profitability"] == {"roe_pct": 12.3}
    assert out["balance_sheet"] is None
    assert out["quality_score"] is None


# ── /api/history/<id> end-to-end DTO normalize ───────────────────────────


def test_history_detail_normalises_rendering_blob(alice_client, app_client):
    """Drop a SNDK-style malformed rendering into the DB; detail DTO
    must surface a sanitised ``rendering`` dict instead of the raw
    payload that crashed the client."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "SNDK", "date": "2026-04-15", "signal": "Sell",
        "trade_decision": "最终评级：Sell（卖出）",
        "created_by": app_client["users"].alice.id,
    })
    # Inject the bad rendering directly.
    bad_rendering = json.dumps({
        "summary": {
            "rating": "Sell", "confidence": "high",
            "action_direction": "Trim", "decision_drivers": "x",
            "one_line_takeaway": "Sell on rallies",
        },
        "Market": {
            "trend": "bearish",
            "support_resistance": [
                {"price": 32.50, "kind": "support"},
                {"price": "—", "kind": "resistance"},
            ],
            "patterns": None,
            "summary": "Resistance at 38, breakdown likely.",
        },
        "Decision": {
            "final_action": "SELL", "conviction": "high", "time_horizon": "short",
            "structural_stop": "—",
            "preconditions": "volume",
            "one_line_summary": "Sell on rallies",
        },
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            (bad_rendering, aid),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    rendering = body["rendering"]

    # ── Survival: the response itself didn't 500 ──────────────────
    assert rendering is not None
    assert "Market" in rendering

    # ── Bad fields normalised ────────────────────────────────────
    market = rendering["Market"]
    assert market["patterns"] == []
    prices = [lvl["price"] for lvl in market["support_resistance"]]
    assert prices == [32.50, None]

    decision = rendering["Decision"]
    assert decision["structural_stop"] is None
    assert decision["preconditions"] == []

    # ── Signal consistency from earlier work still holds ─────────
    assert body["decision_action"] == "Sell"


def test_history_detail_drops_non_dict_card(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "SNDK", "date": "2026-04-15", "signal": "Hold",
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            (json.dumps({
                "summary": "string-not-dict",
                "Market": {"trend": "bullish", "summary": "ok"},
            }), aid),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    rendering = body["rendering"]
    # Bad summary card dropped entirely; Market preserved.
    assert "summary" not in rendering
    assert rendering["Market"]["trend"] == "bullish"
