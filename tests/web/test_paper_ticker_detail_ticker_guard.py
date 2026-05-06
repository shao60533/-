"""paper-trade v1.5.2 — /api/paper/tickers/<ticker> must NOT bleed
trade_decision / advice from a different ticker's analysis row even
when the strategy_event has the wrong analysis_id.

Production saw: AAPL active_plan → analysis #29 (correct), but the
latest strategy_event had analysis_id=30 because the order engine
mistakenly wrote ``order["plan_id"]`` (=30) into the column. The
detail API blindly looked up analysis #30 = SMR's row and surfaced
SMR's trade_decision on AAPL's page.

Even after the order-engine fix in v1.5.2, legacy events still
carry the wrong id until the migration runs. The detail API needs
its own defensive guard: if ``analysis.ticker != page ticker``,
suppress the trade_decision and advice (and log a warning).
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader import PaperTradeStore


def _seed_aapl_smr_collision(app_client) -> int:
    """Reproduce the production scenario:
        analysis #29 = AAPL  (the real, correct one)
        analysis #30 = SMR   (collides with plan_id=30)
        AAPL session strategy_event mis-points at analysis #30.
    Returns alice's user_id.
    """
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id

    aapl_aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-05-06", "signal": "BUY",
        "trade_decision": "AAPL: build base 10-15%, stop 184, target 210",
        "created_by": alice_id,
    })
    smr_aid = db.save_analysis({
        "ticker": "SMR", "date": "2026-05-07", "signal": "BUY",
        "trade_decision": "SMR: speculative entry above 28, stop 22",
        "created_by": alice_id,
    })

    # Sanity-check the production-style id collision: the SMR analysis
    # id should be a number that COULD have been a plan_id mistake.
    assert smr_aid != aapl_aid

    store = PaperTradeStore(app_client["db_path"])
    sid = store.create_ticker_session(
        ticker="AAPL", start_date="2026-05-06", user_id=alice_id,
    )
    # Mis-write: strategy event for AAPL's session points at SMR's
    # analysis id (mirrors the production bug pattern).
    store.insert_strategy_event(
        session_id=sid, analysis_id=smr_aid,
        event_date="2026-05-07",
        prev_signal=None, new_signal="ENTRY_INITIAL",
        action="open", price=190.0,
    )
    return alice_id


def test_detail_suppresses_trade_decision_when_analysis_ticker_mismatches(
    alice_client, app_client,
):
    """The page-ticker guard must drop SMR's trade_decision when the
    page is /api/paper/tickers/AAPL, even if the strategy_event row
    points at SMR's analysis id."""
    _seed_aapl_smr_collision(app_client)

    resp = alice_client.get("/api/paper/tickers/AAPL")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()

    # The bleed gate: latest_trade_decision must NOT be SMR's text.
    decision = body.get("latest_trade_decision") or ""
    assert "SMR" not in decision, (
        f"AAPL page must not surface SMR trade_decision; got {decision!r}"
    )
    assert "speculative entry above 28" not in decision, (
        f"SMR-specific phrase leaked into AAPL detail: {decision!r}"
    )
    # Empty string / None / absence are all acceptable suppressions.
    assert decision == ""

    # latest_advice must also be suppressed.
    assert body.get("latest_advice") in (None, {}, ""), (
        f"latest_advice must be suppressed when ticker mismatches; got "
        f"{body.get('latest_advice')!r}"
    )


def test_detail_returns_correct_decision_when_analysis_matches(
    alice_client, app_client,
):
    """Sanity check the guard doesn't over-trigger: a strategy_event
    pointing at the CORRECT analysis (matching ticker) still surfaces
    the trade_decision."""
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    aid = db.save_analysis({
        "ticker": "MSFT", "date": "2026-05-06", "signal": "BUY",
        "trade_decision": "MSFT: cloud growth thesis, entry 410-420",
        "created_by": alice_id,
    })
    store = PaperTradeStore(app_client["db_path"])
    sid = store.create_ticker_session(
        ticker="MSFT", start_date="2026-05-06", user_id=alice_id,
    )
    store.insert_strategy_event(
        session_id=sid, analysis_id=aid,
        event_date="2026-05-07",
        prev_signal=None, new_signal="ENTRY_INITIAL",
        action="open", price=415.0,
    )

    resp = alice_client.get("/api/paper/tickers/MSFT")
    assert resp.status_code == 200
    body = resp.get_json()
    decision = body.get("latest_trade_decision") or ""
    assert "cloud growth thesis" in decision, (
        f"correct analysis match should surface trade_decision; "
        f"got {decision!r}"
    )
