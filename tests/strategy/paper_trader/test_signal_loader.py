"""SignalLoader resolves advice from user_analysis_advice (v1.13 split).

The shared ``analysis_history.advice_json`` column is empty for non-creator
users since v1.13. SignalLoader must therefore pull each user's per-analysis
advice from ``user_analysis_advice`` and only fall back to ``advice_json``
when the reader IS the original creator (or explicitly opts in for legacy
backfill paths).
"""

from __future__ import annotations

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.strategy.paper_trader.signal_loader import SignalLoader


def _seed_analysis(db: PortfolioDatabase, *, ticker: str = "AAPL",
                    date: str = "2026-04-15", signal: str = "BUY",
                    advice_json: str = "",
                    created_by: int | None = None) -> int:
    return db.save_analysis({
        "ticker": ticker, "date": date, "signal": signal,
        "advice_json": advice_json, "created_by": created_by,
    })


def test_signal_loader_reads_user_advice(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = _seed_analysis(db, advice_json="", created_by=1)
    # ``save_user_advice`` reads ``suggested_position_pct`` /
    # ``entry_price_low`` / ``entry_price_high`` from the advice dict and
    # writes them to the canonical short columns; SignalLoader then
    # re-emits both spellings via ``_normalize_advice`` so plan_parser
    # works without coupling to either name.
    db.save_user_advice(
        user_id=1, analysis_id=aid,
        advice={"action": "BUY", "stop_loss": 140,
                "entry_price_low": 145, "entry_price_high": 150,
                "suggested_position_pct": 0.05},
        holdings_snapshot="[]",
    )
    sig = SignalLoader(str(tmp_path / "p.db"), user_id=1).get_one(aid)
    assert sig is not None
    assert sig["advice"]["action"] == "BUY"
    assert sig["advice"]["stop_loss"] == 140
    # dual-key normalization
    assert sig["advice"]["suggested_position_pct"] == 0.05
    assert sig["advice"]["position_pct"] == 0.05
    assert sig["advice"]["entry_low"] == 145
    assert sig["advice"]["entry_price_low"] == 145


def test_signal_loader_legacy_fallback_only_for_creator(tmp_path):
    """Pre-existing legacy rows that escaped migration must still only be
    visible to the original creator. Post-v1.16 ``save_analysis`` no longer
    writes ``advice_json`` so we inject the legacy state via raw SQL to
    simulate a row that was created before the migration ran."""
    import sqlite3
    db_path = str(tmp_path / "p.db")
    db = PortfolioDatabase(db_path)
    aid = _seed_analysis(db, advice_json="", created_by=1)
    # Force the legacy state directly — this is the only way to reach it
    # now that save_analysis closes the shared-advice backdoor.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
            ('{"action":"BUY","reasoning":"alice-only"}', aid),
        )
    # Alice (creator) sees legacy advice via advice_json fallback.
    sig_alice = SignalLoader(db_path, user_id=1).get_one(aid)
    assert sig_alice is not None
    assert sig_alice["advice"].get("action") == "BUY"
    # Bob (non-creator) must see nothing — no leakage.
    sig_bob = SignalLoader(db_path, user_id=2).get_one(aid)
    assert sig_bob is not None
    assert sig_bob["advice"] == {}


def test_signal_loader_normalizes_dual_keys(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = _seed_analysis(db, created_by=1)
    db.save_user_advice(
        user_id=1, analysis_id=aid,
        advice={"suggested_position_pct": 0.1,
                "entry_price_low": 100, "entry_price_high": 110},
        holdings_snapshot="[]",
    )
    sig = SignalLoader(str(tmp_path / "p.db"), user_id=1).get_one(aid)
    assert sig is not None
    # Both spellings are emitted regardless of which the caller uses.
    assert sig["advice"]["position_pct"] == 0.1
    assert sig["advice"]["suggested_position_pct"] == 0.1
    assert sig["advice"]["entry_low"] == 100
    assert sig["advice"]["entry_price_low"] == 100
    assert sig["advice"]["entry_high"] == 110
    assert sig["advice"]["entry_price_high"] == 110


def test_signal_loader_no_user_blocks_legacy_unless_opted_in(tmp_path):
    """Default constructor (no user_id) must NOT silently fall back.

    See ``test_signal_loader_legacy_fallback_only_for_creator`` — legacy
    state is injected via raw SQL to simulate a pre-migration row.
    """
    import sqlite3
    db_path = str(tmp_path / "p.db")
    db = PortfolioDatabase(db_path)
    aid = _seed_analysis(db, advice_json="", created_by=1)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE analysis_history SET advice_json = ? WHERE id = ?",
            ('{"action":"BUY"}', aid),
        )
    # Default — no fallback even though advice_json is present.
    sig_default = SignalLoader(db_path).get_one(aid)
    assert sig_default is not None
    assert sig_default["advice"] == {}
    # Explicit opt-in (used by replay/backfill) — fallback engaged.
    sig_optin = SignalLoader(db_path, allow_legacy_no_user=True).get_one(aid)
    assert sig_optin is not None
    assert sig_optin["advice"].get("action") == "BUY"


def test_signal_loader_load_filters_by_user(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid_a = _seed_analysis(
        db, ticker="AAPL", date="2026-04-15", created_by=1,
    )
    aid_b = _seed_analysis(
        db, ticker="MSFT", date="2026-04-16", created_by=2,
    )
    db.save_user_advice(
        user_id=1, analysis_id=aid_a,
        advice={"action": "BUY"}, holdings_snapshot="[]",
    )
    # Bob has no advice for either analysis.
    rows = SignalLoader(str(tmp_path / "p.db"), user_id=2).load()
    by_id = {r["analysis_id"]: r for r in rows}
    assert by_id[aid_a]["advice"] == {}  # alice's advice; bob can't see
    assert by_id[aid_b]["advice"] == {}  # no per-user advice persisted yet
