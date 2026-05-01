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
