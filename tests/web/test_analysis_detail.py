"""Cross-user advice + bookmark isolation on /api/history/<id>.

v1.14 split per-user advice off analysis_history into ``user_analysis_advice``
and per-user bookmarks into ``analysis_bookmarks``. The shared analysis row
must look the same for every logged-in user; the advice + bookmarked flag
must reflect only the requesting user's data.
"""

from __future__ import annotations

import sqlite3

import pytest


def _seed_shared_analysis(app_client, *, owner_id: int, ticker="AAPL") -> int:
    """Insert a shared analysis_history row and return its id."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-30", "signal": "BUY",
        "market_report": "shared market notes",
        "sentiment_report": "shared sentiment",
        "news_report": "", "fundamentals_report": "",
        "investment_debate": "", "risk_assessment": "",
        "trade_decision": "go long",
        "advice_json": "",  # NB: per-user advice does NOT live here in v1.14
        "model": "gemini-2.5-flash", "provider": "gemini",
        "created_by": owner_id,
        "config_hash": "deadbeef0000",
        "task_id": "fake-task",
        "duration_sec": 12.5,
    })


def test_alice_sees_her_own_advice_and_bookmark(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={
            "action": "BUY", "confidence": "high",
            "suggested_position_pct": 25.0,
            "entry_price_low": 150.0, "entry_price_high": 152.0,
            "stop_loss": 145.0, "take_profit": 170.0,
            "reasoning": "alice-only thesis",
            "risk_warning": "alice-only risk",
        },
        holdings_snapshot='[{"ticker":"AAPL","shares":10,"avg_cost":120}]',
    )
    db.set_bookmark(users.alice.id, aid, True)

    rv = alice.get(f"/api/history/{aid}")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["advice"] is not None
    assert body["advice"]["action"] == "BUY"
    assert body["advice"]["reasoning"] == "alice-only thesis"
    assert body["bookmarked"] is True
    assert body["created_by_name"] == "alice"  # display_name from email prefix


def test_bob_does_not_see_alices_advice(app_client):
    """Same shared analysis row, different reader → no advice leak."""
    users = app_client["users"]
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    # Alice writes her advice + bookmark
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={"action": "BUY", "reasoning": "alice-only"},
        holdings_snapshot="[]",
    )
    db.set_bookmark(users.alice.id, aid, True)

    rv = bob.get(f"/api/history/{aid}")
    assert rv.status_code == 200
    body = rv.get_json()
    # Shared fields visible
    assert body["ticker"] == "AAPL"
    assert body["market_report"] == "shared market notes"
    # Per-user fields hidden — bob has none of his own
    assert body["advice"] in (None, {}), f"bob should see no advice, got {body['advice']!r}"
    assert body["bookmarked"] is False


def test_each_user_owns_their_bookmark_and_advice(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    bob = app_client["make_client"](users.bob_email, users.bob_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)

    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    db.save_user_advice(
        user_id=users.alice.id, analysis_id=aid,
        advice={"action": "BUY", "reasoning": "alice"},
        holdings_snapshot="[]",
    )
    db.save_user_advice(
        user_id=users.bob.id, analysis_id=aid,
        advice={"action": "HOLD", "reasoning": "bob"},
        holdings_snapshot="[]",
    )
    db.set_bookmark(users.bob.id, aid, True)
    db.set_bookmark(users.alice.id, aid, False)

    a_body = alice.get(f"/api/history/{aid}").get_json()
    b_body = bob.get(f"/api/history/{aid}").get_json()
    assert a_body["advice"]["action"] == "BUY"
    assert a_body["advice"]["reasoning"] == "alice"
    assert a_body["bookmarked"] is False
    assert b_body["advice"]["action"] == "HOLD"
    assert b_body["advice"]["reasoning"] == "bob"
    assert b_body["bookmarked"] is True


def test_legacy_advice_json_falls_back_when_no_per_user_row(app_client):
    """Pre-v1.14 rows that wrote advice into analysis_history.advice_json
    must still render — for the original requester only."""
    import json as _json
    aid = _seed_shared_analysis(app_client, owner_id=app_client["users"].alice.id)
    # Manually backfill legacy column to simulate a pre-v1.14 row.
    conn = sqlite3.connect(app_client["db_path"])
    conn.execute(
        "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
        (_json.dumps({"action": "SELL", "reasoning": "legacy"}), aid),
    )
    conn.commit()
    conn.close()

    alice = app_client["make_client"](
        app_client["users"].alice_email, app_client["users"].alice_password,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["advice"]["action"] == "SELL"
    assert body["advice"]["reasoning"] == "legacy"


# ── analysis-rendering v1.7 — confidence-source semantics ─────────────


def _set_rendering(app_client, aid: int, rendering: dict) -> None:
    """Backfill ``analysis_history.rendering_json`` for one row."""
    import json as _json
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET rendering_json = ? WHERE id = ?",
            (_json.dumps(rendering, ensure_ascii=False), aid),
        )


def _set_advice_confidence(app_client, *, user_id: int, aid: int,
                            level: str) -> None:
    """Plant a per-user advice row with the legacy heuristic confidence
    so we can prove the detail endpoint ignores it post-v1.7."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    db.save_user_advice(
        user_id=user_id, analysis_id=aid,
        advice={
            "action": "BUY", "confidence": level,
            "suggested_position_pct": 25.0,
            "reasoning": "from strategy engine heuristic",
        },
        holdings_snapshot="[]",
    )


def test_detail_confidence_uses_overview_summary_high(app_client):
    """rendering.summary.confidence=high → confidence=0.85 + level=high
    + source=llm_structured_output. This is the canonical v1.7 path."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)
    # Provide a minimal but well-formed OverviewCard so the v1.21
    # client-side normalizer accepts it (rating + action_direction +
    # confidence + one_line_takeaway are required).
    _set_rendering(app_client, aid, {
        "summary": {
            "rating": "Buy",
            "action_direction": "分批建仓",
            "confidence": "high",
            "key_metrics": [],
            "decision_drivers": [],
            "one_line_takeaway": "AI 高置信看多",
        },
    })

    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["confidence"] == 0.85
    assert body["confidence_level"] == "high"
    assert body["confidence_source"] == "llm_structured_output"


def test_detail_confidence_falls_back_to_decision_conviction(app_client):
    """Overview missing → fall back to Decision.conviction. Used by
    rows whose Overview extraction failed but Decision succeeded."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)
    _set_rendering(app_client, aid, {
        # No "summary" key at all — only DecisionCard fields.
        "Decision": {
            "final_action": "Hold",
            "conviction": "low",
            "time_horizon": "1-3 months",
        },
    })

    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["confidence"] == 0.25
    assert body["confidence_level"] == "low"
    assert body["confidence_source"] == "llm_structured_output"


def test_detail_confidence_is_null_without_rendering_and_ignores_advice(
    app_client,
):
    """No rendering_json + an advice.confidence=high planted in
    user_analysis_advice — detail.confidence MUST stay ``null`` so the
    AI analysis confidence never inherits the StrategyEngine heuristic.
    This is the load-bearing v1.7 contract: advice → execution
    confidence (paper-trade only); rendering → analysis confidence."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)
    # No _set_rendering call — rendering_json stays empty.
    _set_advice_confidence(
        app_client, user_id=users.alice.id, aid=aid, level="high",
    )

    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["confidence"] is None
    assert body["confidence_level"] is None
    assert body["confidence_source"] is None
    # advice.confidence is still surfaced under ``advice`` (it's the
    # per-user execution confidence) — but it must NOT bleed into the
    # top-level confidence fields.
    assert body["advice"]["confidence"] == "high"


def test_inbox_completed_row_carries_llm_confidence(app_client):
    """``/api/history?include_running=true`` projects the LLM
    confidence onto each completed row so the inbox chip can render
    without N+1 detail fetches."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)
    _set_rendering(app_client, aid, {
        "summary": {
            "rating": "Buy",
            "action_direction": "建仓",
            "confidence": "medium",
            "key_metrics": [],
            "decision_drivers": [],
            "one_line_takeaway": "中等置信看多",
        },
    })

    body = alice.get("/api/history?include_running=true").get_json()
    row = next(it for it in body["items"]
               if it["kind"] == "analysis" and it["id"] == aid)
    assert row["confidence"] == 0.5
    assert row["confidence_level"] == "medium"
    assert row["confidence_source"] == "llm_structured_output"


def test_inbox_row_confidence_null_when_rendering_missing(app_client):
    """Rows without rendering_json expose ``confidence: null`` rather
    than fabricating one from advice — same contract as the detail
    endpoint, applied to the list shape."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)

    aid = _seed_shared_analysis(app_client, owner_id=users.alice.id)
    _set_advice_confidence(
        app_client, user_id=users.alice.id, aid=aid, level="high",
    )

    body = alice.get("/api/history?include_running=true").get_json()
    row = next(it for it in body["items"]
               if it["kind"] == "analysis" and it["id"] == aid)
    assert row["confidence"] is None
    assert row["confidence_level"] is None
    assert row["confidence_source"] is None
