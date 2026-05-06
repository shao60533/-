"""paper-trade v1.5.2 — strategy_event.analysis_id resolution.

Locks the canonical contract that ``paper_trade_strategy_events.analysis_id``
ALWAYS references ``analysis_history.id``, never ``paper_trade_plans.id``.

Pre-v1.5.2 ``order_engine._execute_order`` and the invalid_stop guard
both wrote ``order["plan_id"]`` directly into the column. Production
saw AAPL plan #30 collide with analysis #30 (SMR), and the detail
API surfaced SMR's trade_decision on AAPL's page.

These tests prove:
    1. ``_resolve_analysis_id`` reads through the plan to fetch the
       canonical analysis_history.id.
    2. With a fake store where plan_id ≠ analysis_id, the resolver
       returns analysis_id (not plan_id).
    3. The migration script's polluted-event detector picks up the
       v1.5.1 mis-write pattern and skips already-correct rows.
"""

from __future__ import annotations

import sqlite3

from stock_trading_system.strategy.paper_trader.order_engine import (
    _resolve_analysis_id,
)
from stock_trading_system.migrations.fix_strategy_event_analysis_id import (
    find_polluted_events, apply_backfill,
)


# ── _resolve_analysis_id ────────────────────────────────────────────


class _FakeStore:
    """Minimal store stub: ``get_plan(plan_id)`` returns a dict with
    ``analysis_id``."""

    def __init__(self, plans: dict[int, dict | None]):
        self._plans = plans

    def get_plan(self, plan_id):
        return self._plans.get(int(plan_id))


def test_resolve_reads_analysis_id_through_plan():
    """Production AAPL bug: plan #30 → analysis_id=29 (AAPL).
    Pre-fix the engine wrote 30 (=plan_id, =SMR analysis #30).
    Post-fix the resolver returns 29."""
    store = _FakeStore({30: {"id": 30, "analysis_id": 29, "ticker": "AAPL"}})
    order = {"id": 1, "plan_id": 30, "order_type": "entry_initial"}
    assert _resolve_analysis_id(store, order) == 29


def test_resolve_falls_back_to_zero_when_plan_missing():
    """A planned order pointing at a deleted plan must NOT bleed plan_id
    into analysis_id — return the safe sentinel 0."""
    store = _FakeStore({})
    order = {"id": 2, "plan_id": 99, "order_type": "exit_stop"}
    assert _resolve_analysis_id(store, order) == 0


def test_resolve_falls_back_to_zero_when_plan_has_no_analysis_id():
    store = _FakeStore({5: {"id": 5, "analysis_id": None}})
    order = {"id": 3, "plan_id": 5, "order_type": "exit_target"}
    assert _resolve_analysis_id(store, order) == 0


def test_resolve_returns_zero_when_plan_id_missing():
    store = _FakeStore({})
    order = {"id": 4, "order_type": "entry_initial"}
    assert _resolve_analysis_id(store, order) == 0


def test_resolve_returns_zero_when_plan_id_is_zero():
    store = _FakeStore({})
    order = {"id": 5, "plan_id": 0, "order_type": "entry_initial"}
    assert _resolve_analysis_id(store, order) == 0


def test_resolve_handles_store_get_plan_exception():
    """A broken store (e.g. missing table in a stripped test DB) must
    NOT crash the order engine — return 0 and log."""

    class _BrokenStore:
        def get_plan(self, plan_id):
            raise sqlite3.OperationalError("no such table: paper_trade_plans")

    order = {"id": 6, "plan_id": 99}
    assert _resolve_analysis_id(_BrokenStore(), order) == 0


# ── Migration backfill ──────────────────────────────────────────────


def _seed_polluted_db(db_path: str) -> None:
    """Build a tiny DB that mirrors the production AAPL→SMR scenario:
    AAPL plan #30 → analysis #29; SMR analysis #30; one strategy
    event mis-wrote analysis_id=30 (plan_id) instead of 29."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE paper_trade_plans (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            analysis_id INTEGER,
            rating TEXT,
            created_at TEXT
        );
        CREATE TABLE paper_trade_strategy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            analysis_id INTEGER,
            event_date TEXT,
            action TEXT
        );
        CREATE TABLE analysis_history (
            id INTEGER PRIMARY KEY,
            ticker TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO analysis_history (id, ticker) VALUES (?, ?)",
        [(29, "AAPL"), (30, "SMR")],
    )
    conn.execute(
        "INSERT INTO paper_trade_plans (id, session_id, analysis_id, "
        "rating, created_at) VALUES (?, ?, ?, ?, ?)",
        (30, 1, 29, "BUY", "2026-05-07"),
    )
    # The polluted event: analysis_id=30 (=plan_id), SHOULD be 29.
    conn.execute(
        "INSERT INTO paper_trade_strategy_events "
        "(session_id, analysis_id, event_date, action) "
        "VALUES (?, ?, ?, ?)",
        (1, 30, "2026-05-07", "open"),
    )
    # A correct event for control: analysis_id=29 already.
    conn.execute(
        "INSERT INTO paper_trade_strategy_events "
        "(session_id, analysis_id, event_date, action) "
        "VALUES (?, ?, ?, ?)",
        (1, 29, "2026-05-06", "open"),
    )
    conn.commit()
    conn.close()


def test_find_polluted_events_picks_up_plan_id_collision(tmp_path):
    db_path = str(tmp_path / "polluted.db")
    _seed_polluted_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = find_polluted_events(conn)
    conn.close()

    # Only the polluted event (analysis_id=30 collides with plan #30)
    # should surface; the correct event (analysis_id=29, no plan #29)
    # is skipped.
    assert len(rows) == 1
    row = rows[0]
    assert row["event_analysis_id"] == 30
    assert row["plan_real_analysis_id"] == 29
    assert row["plan_id"] == 30


def test_apply_backfill_fixes_polluted_events(tmp_path):
    db_path = str(tmp_path / "polluted.db")
    _seed_polluted_db(db_path)
    summary = apply_backfill(db_path, dry_run=False)
    assert summary["checked"] == 1
    assert summary["fixed"] == 1
    # Verify the row was actually rewritten.
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT analysis_id FROM paper_trade_strategy_events ORDER BY id"
    ).fetchall()
    conn.close()
    # First event (was analysis_id=30) is now 29; second event
    # (was analysis_id=29) is unchanged.
    assert rows == [(29,), (29,)]


def test_apply_backfill_dry_run_does_not_mutate(tmp_path):
    db_path = str(tmp_path / "polluted.db")
    _seed_polluted_db(db_path)
    summary = apply_backfill(db_path, dry_run=True)
    assert summary["checked"] == 1
    assert summary["fixed"] == 0
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT analysis_id FROM paper_trade_strategy_events ORDER BY id"
    ).fetchall()
    conn.close()
    # Polluted row still has the wrong value.
    assert rows == [(30,), (29,)]


def test_apply_backfill_idempotent(tmp_path):
    """Running the migration twice MUST be a no-op the second time."""
    db_path = str(tmp_path / "polluted.db")
    _seed_polluted_db(db_path)
    apply_backfill(db_path)
    summary2 = apply_backfill(db_path)
    assert summary2["checked"] == 0
    assert summary2["fixed"] == 0
