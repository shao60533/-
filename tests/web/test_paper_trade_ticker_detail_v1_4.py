"""paper-trade v1.4 — /api/paper/tickers/<ticker> structured-decision contract.

Pins three new contract bits:
  1. ``_signal_to_tri_state`` collapses the LLM's 7-tier rating onto
     {Buy, Sell, Hold} with Sell-side wins for ``Underweight`` (the
     legacy bug where ``"buy" in "underweight"`` mis-classified).
  2. ``active_plan.analysis_summary`` carries the OverviewCard-derived
     banner DTO (signal_tri / executive_summary / confidence pct &
     level / etc.) so the React ActiveStrategyCard renders identically
     to /analysis/<id>.
  3. ``plan_history`` rows ship ``analysis_summary`` and have lost the
     legacy ``trade_decision`` raw markdown; ``latest_trade_decision``
     stays as ``null`` for back-compat while ``latest_analysis_summary``
     is the new canonical field.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from stock_trading_system.web.app import _signal_to_tri_state
from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader import PaperTradeStore


# ── unit: tri-state mapping ─────────────────────────────────────────


def test_signal_to_tri_state_underweight_is_sell_not_buy():
    """``Underweight`` contains ``weight``; the original naive
    ``"buy" in s`` check matched ``buy`` from "Underweight". Sell-side
    tokens MUST be checked first so the tri-state mapping doesn't
    flip Sell → Buy."""
    assert _signal_to_tri_state("Underweight") == "Sell"
    assert _signal_to_tri_state("underweight") == "Sell"
    assert _signal_to_tri_state("Strong Buy") == "Buy"
    assert _signal_to_tri_state("Overweight") == "Buy"
    assert _signal_to_tri_state("Hold") == "Hold"
    assert _signal_to_tri_state("") == "Hold"
    assert _signal_to_tri_state(None) == "Hold"


# ── integration: ticker-detail DTO ──────────────────────────────────


@pytest.fixture
def seeded_msft(app_client):
    """Seed an analysis_history row with rendering_json + executive_summary,
    a paper_trade_session for MSFT, a strategy_event linked to that
    analysis, and one ``paper_trade_plans`` row pointing at the same
    analysis_id. Returns a dict of ids the tests assert against.
    """
    db_path = app_client["db_path"]
    alice_id = app_client["users"].alice.id

    db = PortfolioDatabase(db_path)
    aid = db.save_analysis({
        "ticker": "MSFT", "date": "2026-05-04",
        "signal": "Overweight",
        "created_by": alice_id,
        "trade_decision": "go long with structural stop at 380",
    })

    # Rendering JSON shape mirrors the OverviewCard schema. Use a
    # ``confidence`` enum string since the schema literal is
    # high|medium|low; the bridge helper maps that to 0.85 + level.
    rendering = {
        "summary": {
            "rating": "买入",
            "action_direction": "分批建仓",
            "confidence": "high",
            "key_metrics": [],
            "decision_drivers": [],
            "one_line_takeaway": "MSFT 估值已 reset 至历史中位",
        },
    }
    # Ensure paper-trade v1.3 F3 ``executive_summary`` column exists —
    # older test DB snapshots predate the migration; the production
    # boot path runs paper_trade_v1_3.run_migration() but unit tests
    # construct the schema lazily and don't pick that up.
    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(analysis_history)",
            ).fetchall()
        }
        if "executive_summary" not in cols:
            conn.execute(
                "ALTER TABLE analysis_history "
                "ADD COLUMN executive_summary TEXT",
            )
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ?, "
            "executive_summary = ? WHERE id = ?",
            (
                json.dumps(rendering, ensure_ascii=False),
                "公司 AI 资本支出可由现金流轻松覆盖",
                aid,
            ),
        )

    # Session + event linking the analysis to a paper-trade ticker.
    store = PaperTradeStore(db_path)
    sid = store.create_ticker_session(
        ticker="MSFT", start_date="2026-05-01", user_id=alice_id,
    )
    store.insert_strategy_event(
        session_id=sid, analysis_id=aid,
        event_date="2026-05-04",
        prev_signal=None, new_signal="BUY", action="enter",
        price=420.0,
    )
    plan_id = store.save_plan(
        session_id=sid, analysis_id=aid,
        rating="Overweight",
        thesis="placeholder regex thesis",
        holding_months=(6, 12),
        raw_summary=None,
        plan={"orders": []},
        parse_method="regex",
    )

    return {
        "analysis_id": aid,
        "session_id": sid,
        "plan_id": plan_id,
    }


def test_active_plan_carries_analysis_summary(alice_client, seeded_msft):
    resp = alice_client.get("/api/paper/tickers/MSFT").get_json()
    ap = resp["active_plan"]
    assert ap is not None, resp
    summary = ap["analysis_summary"]
    assert summary is not None
    assert summary["analysis_id"] == seeded_msft["analysis_id"]
    assert summary["signal_tri"] in ("Buy", "Sell", "Hold")
    assert summary["signal_tri"] == "Buy"  # "Overweight" → Buy
    assert summary["executive_summary"]
    assert summary["rating"] == "买入"
    assert summary["action_direction"] == "分批建仓"
    # high → 85 + level=high so the React ConfidenceMeter ring colour
    # matches the /analysis/<id> page.
    assert summary["confidence_level"] == "high"
    assert summary["confidence_pct"] == 85


def test_plan_history_no_longer_contains_trade_decision(
    alice_client, seeded_msft,
):
    resp = alice_client.get("/api/paper/tickers/MSFT").get_json()
    plans = resp["plan_history"]
    assert plans, "fixture should have planted at least one plan"
    for row in plans:
        # v1.4 contract: raw markdown removed.
        assert not row.get("trade_decision"), (
            "v1.4: trade_decision raw markdown 必须移除"
        )
        # And replaced with the structured banner DTO.
        assert "analysis_summary" in row


def test_latest_trade_decision_field_is_now_none(
    alice_client, seeded_msft,
):
    resp = alice_client.get("/api/paper/tickers/MSFT").get_json()
    # Back-compat: legacy clients still see the key but it's null.
    assert resp["latest_trade_decision"] is None
    # New clients consume latest_analysis_summary.
    summary = resp["latest_analysis_summary"]
    assert summary is not None
    assert summary["analysis_id"] == seeded_msft["analysis_id"]
