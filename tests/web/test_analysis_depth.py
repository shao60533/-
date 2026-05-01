"""depth (quick / standard / deep) end-to-end persistence + DTO contract.

The shared analysis_history row carries a ``depth`` column persisted by
both ``PortfolioDatabase.save_analysis`` and
``TaskStore._save_analysis_result``. Unknown / missing values fall back
to ``standard``. The /api/history list and /api/history/<id> detail
DTOs both surface ``depth`` so the React detail page can show it.
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.portfolio.database import (
    PortfolioDatabase,
    _normalize_depth,
)


@pytest.mark.parametrize("incoming,expected", [
    (None,         "standard"),
    ("",           "standard"),
    ("Quick",      "quick"),
    ("standard",   "standard"),
    ("DEEP",       "deep"),
    ("invalid",    "standard"),
    (42,           "standard"),
])
def test_normalize_depth_canonical_set(incoming, expected):
    assert _normalize_depth(incoming) == expected


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


def test_save_analysis_invalid_depth_falls_back_to_standard(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "ultra-deep",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard"


def test_history_list_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "quick",
    })
    body = alice_client.get("/api/history?limit=5").get_json()
    assert body["items"], "list must return at least one item"
    assert body["items"][0]["depth"] == "quick"


def test_history_detail_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "deep"


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


def test_analyzer_iteration_toggle_quick_vs_deep(tmp_path):
    """``analyze(depth='quick')`` must force iteration off even when
    config.iteration.enabled=True; ``depth='deep'`` must force on even
    when config disables it."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})

    # Standard defers to config.
    analyzer._depth_override = "standard"
    assert analyzer._iteration_enabled is True

    # Quick overrides config-on.
    analyzer._depth_override = "quick"
    assert analyzer._iteration_enabled is False

    # Deep overrides config-off.
    analyzer2 = StockAnalyzer({"iteration": {"enabled": False}})
    analyzer2._depth_override = "deep"
    assert analyzer2._iteration_enabled is True
