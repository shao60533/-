"""Phase 1 tests: emit_event + task_events persistence + seq ordering."""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.tasks import event_emitter
from stock_trading_system.tasks.event_emitter import emit_event, get_events_since
from stock_trading_system.migrations.task_events_v1 import migrate


@pytest.fixture(autouse=True)
def _reset_seq_cache():
    """Reset the module-level seq cache between tests."""
    event_emitter._seq_cache.clear()
    yield
    event_emitter._seq_cache.clear()


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, type TEXT, status TEXT,
            created_by INTEGER, created_at TEXT
        );
        INSERT INTO tasks VALUES ('task-1', 'analysis', 'running', 1, '2026-04-20');
        INSERT INTO tasks VALUES ('task-2', 'screen_v3', 'running', 2, '2026-04-20');
    """)
    conn.close()
    migrate(path)
    return path


class TestEmitEvent:
    def test_basic_emit(self, db_path):
        env = emit_event("task-1", "task_progress", {"progress": 0.5}, db_path=db_path, user_id=1)
        assert env is not None
        assert env["task_id"] == "task-1"
        assert env["user_id"] == 1
        assert env["seq"] == 1
        assert env["event"] == "task_progress"
        assert env["payload"]["progress"] == 0.5
        assert "emitted_at" in env

    def test_envelope_has_six_fields(self, db_path):
        env = emit_event("task-1", "test", {}, db_path=db_path, user_id=1)
        required = {"task_id", "user_id", "seq", "event", "payload", "emitted_at"}
        assert required.issubset(set(env.keys()))

    def test_seq_increments(self, db_path):
        e1 = emit_event("task-1", "a", {}, db_path=db_path, user_id=1)
        e2 = emit_event("task-1", "b", {}, db_path=db_path, user_id=1)
        e3 = emit_event("task-1", "c", {}, db_path=db_path, user_id=1)
        assert e1["seq"] == 1
        assert e2["seq"] == 2
        assert e3["seq"] == 3

    def test_seq_independent_per_task(self, db_path):
        e1 = emit_event("task-1", "a", {}, db_path=db_path, user_id=1)
        e2 = emit_event("task-2", "a", {}, db_path=db_path, user_id=2)
        assert e1["seq"] == 1
        assert e2["seq"] == 1  # independent counter

    def test_persisted_to_db(self, db_path):
        emit_event("task-1", "guru_unit_done", {"guru": "buffett"}, db_path=db_path, user_id=1)
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id='task-1'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_resolves_user_id_from_task(self, db_path):
        env = emit_event("task-1", "test", {}, db_path=db_path)
        assert env["user_id"] == 1

    def test_unknown_task_returns_none(self, db_path):
        env = emit_event("nonexistent", "test", {}, db_path=db_path)
        assert env is None


class TestGetEventsSince:
    def test_returns_events_after_seq(self, db_path):
        emit_event("task-1", "a", {"step": 1}, db_path=db_path, user_id=1)
        emit_event("task-1", "b", {"step": 2}, db_path=db_path, user_id=1)
        emit_event("task-1", "c", {"step": 3}, db_path=db_path, user_id=1)

        events = get_events_since(db_path, "task-1", 1, since_seq=1)
        assert len(events) == 2
        assert events[0]["seq"] == 2
        assert events[1]["seq"] == 3

    def test_returns_empty_when_caught_up(self, db_path):
        emit_event("task-1", "a", {}, db_path=db_path, user_id=1)
        events = get_events_since(db_path, "task-1", 1, since_seq=1)
        assert events == []

    def test_user_isolation(self, db_path):
        emit_event("task-1", "a", {}, db_path=db_path, user_id=1)
        emit_event("task-2", "b", {}, db_path=db_path, user_id=2)
        events = get_events_since(db_path, "task-2", 1, since_seq=0)
        assert events == []  # user 1 can't see user 2's events


class TestMigrationIdempotent:
    def test_second_run(self, db_path):
        result = migrate(db_path)
        assert result["status"] == "already_migrated"
