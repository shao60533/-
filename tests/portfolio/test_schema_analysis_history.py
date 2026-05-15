"""hardening-iteration-v1 P3.5 — single source of truth for analysis_history schema.

Pre-P3.5 the CREATE TABLE statement for analysis_history existed in two
places (PortfolioDatabase._init_tables AND TaskStore._ensure_analysis_history_table)
and they drifted — task_store's CREATE missed the rendering_status /
rendering_error / rendering_generated_at columns; only the ALTER drift-
fix loop hid that fact at boot, and only if the loop ran before any
INSERT.

The schema + ALTER list now live in
``stock_trading_system.portfolio._schema_analysis_history``. Both
PortfolioDatabase and TaskStore route through ``ensure_analysis_history``.
This suite locks down that contract.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ── Schema completeness ───────────────────────────────────────────────────


def test_ensure_creates_fresh_table_with_every_column():
    """A fresh DB → calling ensure_analysis_history once → table has
    every column from both CREATE_TABLE and ALTERS."""
    from stock_trading_system.portfolio._schema_analysis_history import (
        ensure_analysis_history, ALTERS,
    )

    conn = sqlite3.connect(":memory:")
    ensure_analysis_history(conn)
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}

    # Every ALTER column must be present after the initial run.
    for name, _ in ALTERS:
        assert name in cols, f"missing column {name!r} after ensure()"

    # Spot-check the rendering_status state-machine columns that
    # task_store used to miss in its inline CREATE.
    assert "rendering_status" in cols
    assert "rendering_error" in cols
    assert "rendering_generated_at" in cols


def test_ensure_is_idempotent():
    """Calling ensure twice changes nothing on the second pass."""
    from stock_trading_system.portfolio._schema_analysis_history import (
        ensure_analysis_history,
    )

    conn = sqlite3.connect(":memory:")
    ensure_analysis_history(conn)
    first = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}
    ensure_analysis_history(conn)
    second = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}
    assert first == second


def test_ensure_retrofits_minimal_existing_table():
    """Simulate a pre-P3.5 DB where only the basic columns exist (old
    schema). ensure() must ALTER in every new column."""
    from stock_trading_system.portfolio._schema_analysis_history import (
        ensure_analysis_history, ALTERS,
    )

    conn = sqlite3.connect(":memory:")
    # Pre-P3.5 minimal subset — the original analysis_history schema
    # before rendering_status / created_by / depth / etc. were added.
    conn.execute("""
        CREATE TABLE analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            signal TEXT NOT NULL,
            market_report TEXT,
            sentiment_report TEXT,
            news_report TEXT,
            fundamentals_report TEXT,
            investment_debate TEXT,
            risk_assessment TEXT,
            trade_decision TEXT,
            advice_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # Before ensure: missing the modern columns.
    before = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}
    for name, _ in ALTERS:
        if name not in before:
            break
    else:
        pytest.fail("test prerequisite broken: minimal schema has all columns")

    ensure_analysis_history(conn)
    after = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}
    for name, _ in ALTERS:
        assert name in after, f"ensure() didn't ALTER in {name!r}"


# ── Drift guard ────────────────────────────────────────────────────────────


def test_portfolio_database_and_task_store_share_one_schema_module():
    """Defensive: both classes must import ``ensure_analysis_history``
    rather than carrying their own inline CREATE/ALTER statements."""
    from stock_trading_system.portfolio import database as pdb
    from stock_trading_system.tasks import task_store as ts

    pdb_src = Path(pdb.__file__).read_text(encoding="utf-8")
    ts_src = Path(ts.__file__).read_text(encoding="utf-8")

    # Both files must reference the central helper.
    assert "_schema_analysis_history" in pdb_src, \
        "portfolio.database lost the _schema_analysis_history import"
    assert "_schema_analysis_history" in ts_src, \
        "tasks.task_store lost the _schema_analysis_history import"

    # And neither should carry a top-level CREATE TABLE for
    # analysis_history any more — that would re-open the drift.
    import re
    pat = re.compile(r"CREATE TABLE.*analysis_history", re.IGNORECASE)
    # task_store had its own; the regex must NOT find one any more.
    matches = pat.findall(ts_src)
    assert not matches, "task_store still has an inline CREATE TABLE analysis_history"
