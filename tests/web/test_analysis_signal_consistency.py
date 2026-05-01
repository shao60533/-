"""DTO surfaces v1.20 ``decision_action`` + ``signal_mismatch`` so the
frontend can reconcile legacy rows where ``signal`` drifted from the
trader's ``FINAL TRANSACTION PROPOSAL: **X**``.
"""

from __future__ import annotations

import sqlite3


def _seed(app_client, *, signal: str, trade_decision: str,
           owner_id: int, ticker: str = "AAPL") -> int:
    """Insert a shared analysis row with the given signal / trade_decision
    pair. The PortfolioDatabase wrapper drops per-user advice columns
    automatically (post-v1.16), so this just covers the shared surface."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-30", "signal": signal,
        "trade_decision": trade_decision,
        "market_report": "shared market notes",
        "created_by": owner_id,
    })


def test_dto_emits_decision_action_when_decision_parses(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client,
        signal="Sell",
        trade_decision="Trader thesis.\n\nFINAL TRANSACTION PROPOSAL: **SELL**",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Sell"
    # Stored signal already matches → no mismatch flag.
    assert body["signal_mismatch"] is False


def test_dto_flags_mismatch_when_signal_drifts(app_client):
    """Legacy row scenario — DB has signal=Hold but trader text said SELL.
    DTO must surface the drift so the UI can correct itself."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client,
        signal="Hold",  # ← stale / wrong (graph.process_signal disagreed)
        trade_decision="FINAL TRANSACTION PROPOSAL: **SELL**",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["signal"] == "Hold"
    assert body["decision_action"] == "Sell"
    assert body["signal_mismatch"] is True


def test_dto_no_mismatch_when_decision_unparseable(app_client):
    """``graph.process_signal`` returns OVERWEIGHT / UNDERWEIGHT for
    nuanced calls that ``extract_trade_action`` deliberately doesn't try
    to classify. With no parseable trader proposal, we pass through
    ``signal`` unchanged and keep ``signal_mismatch=false``."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client,
        signal="OVERWEIGHT",
        trade_decision="Mixed picture; awaiting next earnings.",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["signal"] == "OVERWEIGHT"
    assert body["decision_action"] is None
    assert body["signal_mismatch"] is False


def test_dto_no_mismatch_when_signal_already_matches(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client,
        signal="Hold",
        trade_decision="FINAL TRANSACTION PROPOSAL: **HOLD**",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Hold"
    assert body["signal_mismatch"] is False


def test_dto_case_insensitive_match(app_client):
    """``signal`` may be stored as ``"BUY"`` (legacy) while the v1.20
    canon produces ``"Buy"``. Mismatch detection compares case-blind."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client,
        signal="BUY",  # uppercase legacy
        trade_decision="FINAL TRANSACTION PROPOSAL: **BUY**",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Buy"
    # Same action, different case → not a mismatch.
    assert body["signal_mismatch"] is False


def test_dto_other_reports_mentioning_buy_do_not_mask_sell_decision(app_client):
    """Spec: BUY/SELL inside fundamentals/news must not affect the
    canonical action — only ``trade_decision`` is parsed."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-30",
        "signal": "Hold",  # stale
        "trade_decision": "FINAL TRANSACTION PROPOSAL: **SELL**",
        # Other sections shout BUY — must NOT influence decision_action.
        "fundamentals_report": "Strong **BUY** call from quants.",
        "news_report": "Analyst upgrade to **BUY** rating.",
        "created_by": users.alice.id,
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    # decision_action follows trade_decision only.
    assert body["decision_action"] == "Sell"
    assert body["signal_mismatch"] is True
    # Sanity: fundamentals + news reports surface untouched (no
    # silent rewrite — they're shared research bodies).
    assert "BUY" in body["fundamentals_report"]


def test_dto_handles_missing_trade_decision(app_client):
    """No trade_decision text at all → decision_action=None, mismatch=False."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-30", "signal": "Hold",
        "trade_decision": "",
        "created_by": users.alice.id,
    })
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] is None
    assert body["signal_mismatch"] is False


# ── Storage contract: post-v1.20 saves write canonical signal ────────────

def test_post_v1_20_saves_have_signal_matching_decision(app_client):
    """When ``signal`` is saved as the parsed action, no mismatch ever
    appears in the DTO — proving the analyzer-side override would
    eliminate the issue going forward (legacy rows still flag)."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    from stock_trading_system.agents.iterative.signal_extractor import (
        extract_trade_action,
    )
    decision = "FINAL TRANSACTION PROPOSAL: **SELL**"
    canonical = extract_trade_action(decision)
    assert canonical == "Sell"  # sanity
    aid = _seed(
        app_client, signal=canonical, trade_decision=decision,
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["signal_mismatch"] is False
    assert body["signal"] == "Sell"
    assert body["decision_action"] == "Sell"


# ── Smoke: existing rows keep working through this DTO ───────────────────

def test_dto_does_not_break_existing_detail_fields(app_client):
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client, signal="Buy",
        trade_decision="FINAL TRANSACTION PROPOSAL: **BUY**",
        owner_id=users.alice.id,
    )
    body = alice.get(f"/api/history/{aid}").get_json()
    # New fields exist.
    assert "decision_action" in body
    assert "signal_mismatch" in body
    # Existing fields untouched.
    assert body["ticker"] == "AAPL"
    assert body["market_report"] == "shared market notes"
    # ``signal`` column still surfaces.
    assert body["signal"] == "Buy"


def test_dto_db_row_directly_corrupted(app_client):
    """Pre-v1.20 row inserted via raw SQL with arbitrary signal mismatch."""
    users = app_client["users"]
    alice = app_client["make_client"](users.alice_email, users.alice_password)
    aid = _seed(
        app_client, signal="Hold",
        trade_decision="FINAL TRANSACTION PROPOSAL: **BUY**",
        owner_id=users.alice.id,
    )
    # Belt-and-braces: confirm DB really has the mismatch (so the test
    # would fail loud if the seed silently corrected itself).
    with sqlite3.connect(app_client["db_path"]) as c:
        row = c.execute(
            "SELECT signal, trade_decision FROM analysis_history WHERE id = ?",
            (aid,),
        ).fetchone()
    assert row[0] == "Hold"
    assert "BUY" in (row[1] or "")
    body = alice.get(f"/api/history/{aid}").get_json()
    assert body["decision_action"] == "Buy"
    assert body["signal_mismatch"] is True
