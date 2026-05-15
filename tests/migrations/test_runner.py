"""hardening-iteration-v1 P3.4 — migrations._runner unit tests.

Pre-P3.4 every migration script was a free-standing CLI. Two
"补丁迁移" (fix_strategy_event_analysis_id / fix_tasks_orphan_events)
existed precisely because there was no record of which migrations had
already run on a given DB.

The runner now bookkeeps via ``applied_migrations(name, applied_at,
status)``. This suite locks down:

    1. Fresh DB + run_pending(dry_run) → reports every migration as
       "would run"; nothing is recorded.
    2. mark_baseline + run_pending → baseline-marked names are in
       skipped_done, NOT in ran.
    3. run_pending twice in a row is a no-op the second time (idempotent).
    4. OPT_IN backfills are skipped by default; --include-opt-in
       surfaces them in ran.
    5. status() returns a stable view of applied_migrations + the
       canonical order + opt-in set.
    6. Importing every name in MIGRATIONS exposes a callable
       ``migrate``  (smoke check against future module renames).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stock_trading_system.migrations import _runner


@pytest.fixture
def fresh_db(tmp_path):
    """A bare sqlite file with no schema. The runner builds
    applied_migrations on first access."""
    db = tmp_path / "portfolio.db"
    sqlite3.connect(str(db)).close()
    return str(db)


def test_run_pending_dry_run_reports_all(fresh_db):
    result = _runner.run_pending(fresh_db, dry_run=True)
    assert result["dry_run"] is True
    # Every non-opt-in migration should be in 'ran' under dry_run.
    ran_names = [r["name"] for r in result["ran"]]
    for name in _runner.MIGRATIONS:
        if name in _runner.OPT_IN:
            assert name in result["skipped_opt_in"]
        else:
            assert name in ran_names
    assert result["failed"] == []


def test_run_pending_dry_run_does_not_record(fresh_db):
    _runner.run_pending(fresh_db, dry_run=True)
    conn = sqlite3.connect(fresh_db)
    rows = conn.execute(
        "SELECT name FROM applied_migrations"
    ).fetchall()
    conn.close()
    # dry_run leaves the table empty (the table is created but no rows).
    assert rows == []


def test_mark_baseline_marks_names(fresh_db):
    names = ["to_multi_tenant", "p0a_data_partition", "task_events_v1"]
    n = _runner.mark_baseline(fresh_db, names)
    assert n == 3

    conn = sqlite3.connect(fresh_db)
    rows = conn.execute(
        "SELECT name, status FROM applied_migrations ORDER BY name"
    ).fetchall()
    conn.close()
    assert {(r[0], r[1]) for r in rows} == {(n, "baseline") for n in names}


def test_baseline_marked_names_skipped_on_dry_run(fresh_db):
    """After baseline marking, the dry-run plan should NOT include
    those names — they're treated as done."""
    _runner.mark_baseline(fresh_db, ["to_multi_tenant", "p0a_data_partition"])
    result = _runner.run_pending(fresh_db, dry_run=True)
    skipped = set(result["skipped_done"])
    assert "to_multi_tenant" in skipped
    assert "p0a_data_partition" in skipped


def test_opt_in_skipped_by_default(fresh_db):
    """OPT_IN migrations (heavy backfills) are not auto-run."""
    result = _runner.run_pending(fresh_db, dry_run=True)
    for name in _runner.OPT_IN:
        assert name in result["skipped_opt_in"]
        assert not any(r["name"] == name for r in result["ran"])


def test_opt_in_surfaces_when_requested(fresh_db):
    result = _runner.run_pending(
        fresh_db, dry_run=True, include_opt_in=True,
    )
    ran = {r["name"] for r in result["ran"]}
    for name in _runner.OPT_IN:
        assert name in ran


def test_status_returns_canonical_view(fresh_db):
    _runner.mark_baseline(fresh_db, ["to_multi_tenant"])
    s = _runner.status(fresh_db)
    assert s["canonical_order"] == list(_runner.MIGRATIONS)
    assert set(s["opt_in"]) == set(_runner.OPT_IN)
    applied = {row["name"]: row["status"] for row in s["applied"]}
    assert applied.get("to_multi_tenant") == "baseline"


def test_every_migration_resolves_via_runner_lookup():
    """Defensive: every name in MIGRATIONS must resolve to a callable
    through ``_import_migrate``. Catches future module renames that
    would otherwise only surface at boot."""
    for name in _runner.MIGRATIONS:
        fn = _runner._import_migrate(name)
        assert callable(fn), f"migration {name!r} did not resolve to callable"


def test_run_pending_records_ok_status_on_success(tmp_path, monkeypatch):
    """When a real migration succeeds the row is status='ok'."""
    db = tmp_path / "portfolio.db"
    sqlite3.connect(str(db)).close()

    # Stub one migration so we can exercise the success-recording path
    # without touching DB schema.
    import stock_trading_system.migrations._runner as r

    def fake_import_migrate(name):
        return lambda db_path, dry_run=False: {"status": "ok-stub"}

    monkeypatch.setattr(r, "_import_migrate", fake_import_migrate)
    monkeypatch.setattr(r, "MIGRATIONS", ["fake_one"])
    monkeypatch.setattr(r, "OPT_IN", frozenset())

    result = r.run_pending(str(db))
    assert {x["name"] for x in result["ran"]} == {"fake_one"}
    # Recorded as ok in the table.
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT name, status FROM applied_migrations WHERE name = 'fake_one'"
    ).fetchone()
    conn.close()
    assert row == ("fake_one", "ok")

    # Second run skips it.
    second = r.run_pending(str(db))
    assert second["ran"] == []
    assert "fake_one" in second["skipped_done"]


def test_run_pending_stops_at_first_failure(tmp_path, monkeypatch):
    db = tmp_path / "portfolio.db"
    sqlite3.connect(str(db)).close()

    import stock_trading_system.migrations._runner as r

    def boom(db_path, dry_run=False):
        raise RuntimeError("synthetic boom")

    def fake_import_migrate(name):
        if name == "bad":
            return boom
        return lambda db_path, dry_run=False: {"ok": True}

    monkeypatch.setattr(r, "_import_migrate", fake_import_migrate)
    # ``bad`` is in the middle — anything after it must NOT run.
    monkeypatch.setattr(r, "MIGRATIONS", ["a", "bad", "c"])
    monkeypatch.setattr(r, "OPT_IN", frozenset())

    result = r.run_pending(str(db))
    ran = [x["name"] for x in result["ran"]]
    assert ran == ["a"]  # a succeeded, bad failed, c never ran
    assert len(result["failed"]) == 1
    assert result["failed"][0]["name"] == "bad"
