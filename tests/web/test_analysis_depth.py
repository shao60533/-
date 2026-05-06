"""depth two-state contract — v2.1 collapse from {quick, standard,
deep} to {standard, deep}.

The shared ``analysis_history`` row carries a ``depth`` column written
by both ``PortfolioDatabase.save_analysis`` and
``TaskStore._save_analysis_result``. The user-visible enum is now only
``standard | deep`` — legacy ``quick`` rows / inputs collapse to
``standard`` everywhere (storage, DTO, analyzer iteration toggle).

Frontend canonical input is the boolean ``deep_analysis``. Backend
exposes ``normalize_analysis_depth(params)`` so workers / API routes
read both shapes through one helper.
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.portfolio.database import (
    PortfolioDatabase,
    _normalize_depth,
    normalize_analysis_depth,
    VALID_DEPTHS,
)


# ── _normalize_depth — string coercion ─────────────────────────────────


@pytest.mark.parametrize("incoming,expected", [
    (None,         "standard"),
    ("",           "standard"),
    # v2.1 — quick is no longer a canonical depth. Inputs that still
    # arrive on the wire (stale frontend, stored params_json from old
    # DBs) collapse to standard.
    ("Quick",      "standard"),
    ("quick",      "standard"),
    ("QUICK",      "standard"),
    ("standard",   "standard"),
    ("DEEP",       "deep"),
    ("invalid",    "standard"),
    (42,           "standard"),
])
def test_normalize_depth_canonical_set(incoming, expected):
    assert _normalize_depth(incoming) == expected


def test_valid_depths_constant_is_two_states():
    """Lock the canonical set so a future drift back to 3 states is
    caught at import time. ``quick`` is intentionally excluded — it's
    a legacy alias, not a valid persisted depth."""
    assert VALID_DEPTHS == ("standard", "deep")
    assert "quick" not in VALID_DEPTHS


# ── normalize_analysis_depth — boolean + legacy unifier ────────────────


def test_normalize_analysis_depth_boolean_true_routes_to_deep():
    """Canonical wire shape: deep_analysis=True → depth="deep"."""
    out = normalize_analysis_depth({"deep_analysis": True})
    assert out == {"depth": "deep", "deep_analysis": True}


def test_normalize_analysis_depth_boolean_false_routes_to_standard():
    out = normalize_analysis_depth({"deep_analysis": False})
    assert out == {"depth": "standard", "deep_analysis": False}


def test_normalize_analysis_depth_legacy_string_quick_collapses_to_standard():
    """A stale frontend that still sends ``depth=quick`` (no boolean)
    must NOT carry the deprecated value forward — the helper coerces
    quick → standard so the worker / DB / paper-trade replay only
    ever see two states."""
    out = normalize_analysis_depth({"depth": "quick"})
    assert out == {"depth": "standard", "deep_analysis": False}


def test_normalize_analysis_depth_legacy_string_deep_routes_to_deep():
    out = normalize_analysis_depth({"depth": "deep"})
    assert out == {"depth": "deep", "deep_analysis": True}


def test_normalize_analysis_depth_legacy_string_standard():
    out = normalize_analysis_depth({"depth": "standard"})
    assert out == {"depth": "standard", "deep_analysis": False}


def test_normalize_analysis_depth_boolean_wins_over_legacy_string():
    """When BOTH fields are present (transition window), the boolean
    is the source of truth — that's the contract the React frontend
    relies on (it sends both for one release as a safety net)."""
    out = normalize_analysis_depth({"deep_analysis": True, "depth": "standard"})
    assert out["depth"] == "deep"
    out2 = normalize_analysis_depth({"deep_analysis": False, "depth": "deep"})
    assert out2["depth"] == "standard"


def test_normalize_analysis_depth_non_bool_falls_through():
    """``deep_analysis="true"`` (string) is NOT a real boolean — fall
    through to legacy depth so we don't accidentally promote a string
    to deep mode. Strict-bool gate keeps the contract surface tight."""
    out = normalize_analysis_depth({"deep_analysis": "true", "depth": "standard"})
    assert out == {"depth": "standard", "deep_analysis": False}


def test_normalize_analysis_depth_empty_input_defaults_standard():
    assert normalize_analysis_depth({}) == {"depth": "standard", "deep_analysis": False}
    assert normalize_analysis_depth(None) == {"depth": "standard", "deep_analysis": False}


# ── DB persistence ────────────────────────────────────────────────────


def test_save_analysis_persists_depth(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "deep",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "deep"


def test_save_analysis_defaults_depth_when_missing(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard"


def test_save_analysis_legacy_quick_input_persists_as_standard(tmp_path):
    """A worker that still passes ``depth='quick'`` (e.g. a queued
    task that predates the v2.1 deploy) must NOT write the legacy
    string to disk — _normalize_depth collapses to standard so future
    reads can't be confused about whether quick was a valid run."""
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "quick",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard", (
        "legacy 'quick' input must collapse on write — found 'quick' on "
        "disk would mean the deprecation is leaking into storage"
    )


def test_save_analysis_invalid_depth_falls_back_to_standard(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "ultra-deep",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard"


# ── DTO surface ────────────────────────────────────────────────────────


def test_history_list_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get("/api/history?limit=5").get_json()
    assert body["items"], "list must return at least one item"
    assert body["items"][0]["depth"] == "deep"


def test_history_detail_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "deep"


def test_history_detail_legacy_quick_row_dto_returns_standard(
    alice_client, app_client,
):
    """Pre-v2.1 rows may still have ``depth='quick'`` in storage (the
    DB migration is non-destructive). The DTO must surface ``standard``
    so the React frontend never sees the deprecated value — there's no
    UI control left to render 'quick'."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id,
    })
    # Force-write the legacy value directly (bypassing _normalize_depth)
    # so the test exercises the DTO's read-side normalization.
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET depth = 'quick' WHERE id = ?", (aid,),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "standard", (
        "DTO must collapse legacy 'quick' rows to 'standard' on read"
    )


def test_history_detail_legacy_null_depth_renders_as_standard(
    alice_client, app_client,
):
    """Pre-v1.16 rows have NULL depth — DTO normalises to 'standard'
    so the UI never has to special-case it."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET depth = NULL WHERE id = ?", (aid,),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "standard"


def test_task_store_persists_depth(tmp_path):
    """Workers route results through TaskStore, which is the canonical
    write path. It must persist ``depth`` and normalise unknowns."""
    from stock_trading_system.tasks.task_store import TaskStore
    store = TaskStore(str(tmp_path / "tasks.db"))
    ref = store.save_result("analysis", "task-1", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "deep",
    })
    rid = int(ref.split(":", 1)[1])
    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (rid,),
        ).fetchone()
    assert row["depth"] == "deep"


def test_task_store_collapses_legacy_quick_on_save(tmp_path):
    """Same write-side guard as ``save_analysis`` but via the task
    store path — the helper is shared so both layers collapse legacy
    quick to standard. Catch a future regression where one side
    forgets to call _normalize_depth."""
    from stock_trading_system.tasks.task_store import TaskStore
    store = TaskStore(str(tmp_path / "tasks.db"))
    ref = store.save_result("analysis", "task-2", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "quick",
    })
    rid = int(ref.split(":", 1)[1])
    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (rid,),
        ).fetchone()
    assert row["depth"] == "standard"


# ── Analyzer iteration toggle — depth-only contract ───────────────────


def test_analyzer_standard_forces_iteration_off_even_when_config_enabled():
    """v2.1 — ``standard`` MUST force iteration off regardless of
    ``config.iteration.enabled``. The user-visible 2-state contract
    means a single button has a single behaviour; deferring to a
    YAML toggle would let the same UI click do different things on
    two deployments."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    assert analyzer._iteration_for("standard") is False, (
        "standard must NOT honor config.iteration.enabled — that "
        "was the v2.0 leak the v2.1 cleanup is closing"
    )


def test_analyzer_deep_forces_iteration_on_even_when_config_disabled():
    """The mirror invariant — ``deep`` always means iteration on."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    analyzer = StockAnalyzer({"iteration": {"enabled": False}})
    assert analyzer._iteration_for("deep") is True


def test_analyzer_legacy_quick_routes_to_iteration_off():
    """A legacy queued task that still passes 'quick' must NOT enable
    iteration (would be the worst possible interpretation: the user
    explicitly asked for a fast pass)."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    assert analyzer._iteration_for("quick") is False


def test_analyzer_unknown_depth_defaults_iteration_off():
    """Defensive — an unrecognised depth must default to the safer
    cheaper branch (off), not to deep."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    assert analyzer._iteration_for("ultra-deep") is False
    assert analyzer._iteration_for("") is False
