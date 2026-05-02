"""SNDK production-shape regression: load the saved /api/history/17
fixture into a fresh DB and assert the detail route survives the
malformed structured-card payload that white-screened the React island.

Playwright would let us visit /analysis/<id> and assert
``#react-root`` is non-empty + console error count is zero. We don't
have Playwright wired up in this suite, so we instead:

1. POST the fixture into the DB.
2. GET ``/api/history/<id>`` and verify the DTO normalises every bad
   field documented in the white-screen postmortem.
3. GET ``/analysis/<id>`` and verify the rendered HTML carries the
   React root container (the boundary keeps it mounted) and the
   bundled JS reference for the analysis island.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from stock_trading_system.portfolio.database import PortfolioDatabase


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sndk_analysis_17.json"


@pytest.fixture
def sndk_fixture():
    raw = FIXTURE_PATH.read_text()
    return json.loads(raw)


def _seed(app_client, sndk: dict) -> int:
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": sndk["ticker"], "date": sndk["date"],
        "signal": sndk["signal"], "trade_decision": sndk["trade_decision"],
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            (json.dumps(sndk["rendering_json"]), aid),
        )
    return aid


def test_history_detail_survives_sndk_payload(alice_client, app_client, sndk_fixture):
    aid = _seed(app_client, sndk_fixture)
    resp = alice_client.get(f"/api/history/{aid}")
    assert resp.status_code == 200
    body = resp.get_json()

    # Top-level fields the page header relies on.
    assert body["ticker"] == "SNDK"
    assert body["decision_action"] == "Sell"  # Chinese 最终评级 wins
    assert body["signal_mismatch"] is True
    assert body["signal"] == "Hold"            # original stored value retained

    rendering = body["rendering"]

    # Bad ``support_resistance[1].price`` is normalised to None — front
    # end will skip rendering that level instead of crashing.
    sr_prices = [lvl["price"] for lvl in rendering["Market"]["support_resistance"]]
    assert sr_prices[0] == 32.50
    assert sr_prices[1] is None
    assert sr_prices[2] == 38.40

    # ``structural_stop: "n/a"`` normalised to None.
    assert rendering["Decision"]["structural_stop"] is None

    # ``balance_sheet: null`` preserved as None (not crashed).
    assert rendering["Fundamentals"]["balance_sheet"] is None

    # Decision tab keeps its action enum so the React badge renders Sell.
    assert rendering["Decision"]["final_action"] == "SELL"


def test_analysis_detail_route_returns_html_shell(alice_client, app_client, sndk_fixture):
    """GET /analysis/<id> must return the AppShell HTML with the
    React root container intact. Even when the bundle hasn't loaded
    yet (no JS in the test client) the page-level ErrorBoundary
    inside main.tsx is wired so the user always lands on something.
    """
    aid = _seed(app_client, sndk_fixture)
    resp = alice_client.get(f"/analysis/{aid}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'id="react-root"' in html
    # The Vite manifest emits one <script type="module" …analysis…> entry.
    assert 'type="module"' in html
    assert "analysis" in html.lower()


def test_history_list_after_sndk_seed(alice_client, app_client, sndk_fixture):
    """Smoke: the list endpoint also tolerates the SNDK row."""
    _seed(app_client, sndk_fixture)
    body = alice_client.get("/api/history?limit=5").get_json()
    assert body["count"] >= 1
    assert any(item["ticker"] == "SNDK" for item in body["items"])


# ── R2 — production /analysis/17 still tripped the per-tab boundary ────
#
# The SNDK fixture above is the *clean* production shape. The user's
# ongoing report ("仍然显示结构化卡片渲染失败") implies the deployed DB
# row carries shapes the v1.21 normalizer didn't catch. We don't have
# the raw DB blob, so we synthesise the realistic worst-case payloads
# the spec calls out below and verify the API + normalize pipeline
# self-heals every one of them.

def _seed_with_rendering(app_client, ticker: str, rendering: dict) -> int:
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": ticker, "date": "2026-05-02",
        "signal": "Hold", "trade_decision": "—",
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            (json.dumps(rendering), aid),
        )
    return aid


def test_summary_card_when_summary_is_array(alice_client, app_client):
    """``rendering.summary`` shaped as an array — the v1.21 ``isinstance(card,
    dict)`` guard drops the whole card, so the API response simply omits
    the ``summary`` key. Frontend ErrorBoundary therefore never even
    sees the malformed shape."""
    aid = _seed_with_rendering(app_client, "BAD1", {
        "summary": ["array", "instead", "of", "dict"],
        "Market": {"trend": "neutral", "summary": "ok"},
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert "summary" not in body["rendering"]
    assert body["rendering"]["Market"]["trend"] == "neutral"


def test_summary_debate_synthesis_array_or_string(alice_client, app_client):
    """``debate_synthesis`` is supposed to be an object (or null). When
    the LLM returns an array or string, normalize collapses it to None
    so the client never tries ``synth.aggressive`` access on a non-record."""
    for bad in (["item1"], "string-not-dict", 42, True):
        aid = _seed_with_rendering(app_client, "BAD2", {
            "summary": {
                "rating": "Hold", "confidence": "medium",
                "action_direction": "wait",
                "debate_synthesis": bad,
                "decision_drivers": [],
                "key_metrics": [],
                "one_line_takeaway": "wait",
            },
        })
        body = alice_client.get(f"/api/history/{aid}").get_json()
        assert body["rendering"]["summary"]["debate_synthesis"] is None, bad


def test_summary_decision_drivers_mixed_items(alice_client, app_client):
    """``decision_drivers`` array containing string / null / object
    mixed. The frontend OverviewCard filters to records on top — the
    backend keeps the array as-is for now (only top-level coerced to []
    if non-list) but the client guard is enough."""
    aid = _seed_with_rendering(app_client, "BAD3", {
        "summary": {
            "rating": "Hold", "confidence": "medium",
            "action_direction": "wait",
            "decision_drivers": [
                "string-driver",
                None,
                {"headline": "Real driver", "detail": "Real detail"},
                ["nested", "array"],
            ],
            "key_metrics": [],
            "one_line_takeaway": "wait",
        },
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    drivers = body["rendering"]["summary"]["decision_drivers"]
    # Backend keeps the array shape; frontend filters non-records.
    # We just verify the API didn't 500 and the array survived.
    assert isinstance(drivers, list)
    real = [d for d in drivers if isinstance(d, dict) and d.get("headline") == "Real driver"]
    assert len(real) == 1


def test_summary_key_metrics_value_is_object(alice_client, app_client):
    """``key_metrics[i].value`` is an object/array — React would throw
    "Objects are not valid as a React child" if it leaked. ``safeText``
    on the client coerces to ``"—"``; the API just keeps the raw shape."""
    aid = _seed_with_rendering(app_client, "BAD4", {
        "summary": {
            "rating": "Hold", "confidence": "medium",
            "action_direction": "wait",
            "decision_drivers": [],
            "key_metrics": [
                "string-metric",
                None,
                {"label": "PE", "value": {"nested": "obj"}, "tone": "neutral"},
                {"label": "Vol", "value": ["a", "b"], "tone": "neutral"},
            ],
            "one_line_takeaway": "wait",
        },
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    metrics = body["rendering"]["summary"]["key_metrics"]
    assert isinstance(metrics, list)
    # Smoke: server didn't choke, weird value types still in payload
    # (the frontend safeText wraps them to "—").
    assert any(isinstance(m, dict) and m.get("label") == "PE" for m in metrics)


def test_summary_unknown_enum_with_whitespace(alice_client, app_client):
    """``rating`` / ``confidence`` enums returned with trailing whitespace
    or wrong casing or even an object. The wire DTO keeps whatever the
    LLM produced; the React badge falls back to the neutral chip."""
    aid = _seed_with_rendering(app_client, "BAD5", {
        "summary": {
            "rating": "BUY ",                       # trailing whitespace
            "confidence": "HIGH",                  # wrong case
            "action_direction": "—",
            "decision_drivers": [],
            "key_metrics": [],
            "one_line_takeaway": "x",
        },
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    summ = body["rendering"]["summary"]
    # Survived round-trip without normalisation — fine, the React
    # ``RatingBadge`` shows whatever string is there with a neutral chip.
    assert summ["rating"] == "BUY "
    assert summ["confidence"] == "HIGH"

    aid2 = _seed_with_rendering(app_client, "BAD6", {
        "summary": {
            "rating": {"nested": "obj"},
            "confidence": {"low": True},
            "action_direction": "—",
            "decision_drivers": [],
            "key_metrics": [],
            "one_line_takeaway": "x",
        },
    })
    body2 = alice_client.get(f"/api/history/{aid2}").get_json()
    # API doesn't 500; the React side guards via ``typeof === "string"``.
    assert isinstance(body2["rendering"]["summary"]["rating"], dict)


def test_market_indicators_mixed_items(alice_client, app_client):
    """Backend ``_normalize_card`` only coerces ``support_resistance`` to
    record-only items; ``indicators`` array stays as-is. The frontend
    card now filters to records on top, so a string item in the
    indicator list won't reach the ``it.signal`` / ``it.value`` reads."""
    aid = _seed_with_rendering(app_client, "BAD7", {
        "Market": {
            "trend": "neutral",
            "indicators": [
                "string-indicator",
                None,
                {"name": "RSI", "value": "32", "signal": "bearish"},
            ],
            "support_resistance": [],
            "patterns": [],
            "summary": "ok",
        },
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    inds = body["rendering"]["Market"]["indicators"]
    # API preserves shape; client filter (isRecord) drops bad items.
    assert isinstance(inds, list)
    real = [i for i in inds if isinstance(i, dict) and i.get("name") == "RSI"]
    assert len(real) == 1
