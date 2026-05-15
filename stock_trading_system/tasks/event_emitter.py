"""Unified event emission for all task workers.

emit_event() is the ONLY way workers should push progress to the frontend.
It persists events to task_events table (for catch-up on reconnect) and
broadcasts via SocketIO to the user's room (per-user isolation).

All events follow the standard envelope:
    {task_id, user_id, seq, event, payload, emitted_at}

hardening-iteration-v1 P3.5: seq is now derived from the DB at write
time (``SELECT MAX(seq)+1 WHERE task_id=?``), not an in-memory dict.
Pre-P3.5 the ``_seq_cache`` started empty after every restart, so the
first event a worker wrote post-restart re-used seq=1 — and ``INSERT
OR IGNORE`` happily dropped it on the floor because (task_id, 1)
already lived in the DB. The DB-derived approach plus an opportunistic
``INSERT … UNIQUE`` + retry loop survives both restarts and the
in-flight race between two threads writing for the same task.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from stock_trading_system.utils import get_logger

logger = get_logger("tasks.event_emitter")

# How many times we retry the optimistic INSERT before giving up. Two
# worker threads racing on the same task_id will each grab MAX(seq)+1
# and one of them will lose the UNIQUE-constraint race; in practice
# more than a handful of concurrent writers on the SAME task is
# pathological (a task is one logical run). 8 retries is plenty.
_SEQ_RETRY_LIMIT = 8


def ensure_task_events_table(db_path: str) -> None:
    """Create task_events table + indexes if missing.

    Safe to call at every app startup (idempotent CREATE IF NOT EXISTS).
    Without this, fresh deployments hit `no such table: task_events` on
    the first event-history fetch, surfacing as "加载失败" in the UI.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS task_events ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " task_id TEXT NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " seq INTEGER NOT NULL,"
            " event TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " emitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
            " UNIQUE (task_id, seq));"
            "CREATE INDEX IF NOT EXISTS ix_task_events_user_seq ON task_events(user_id, id DESC);"
            "CREATE INDEX IF NOT EXISTS ix_task_events_task_seq ON task_events(task_id, seq);"
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("ensure_task_events_table failed: %s", e)


def _now_iso() -> str:
    # P2.5: utcnow() deprecated in Py3.12+; route via timez helper which
    # returns a tz-aware UTC datetime under the hood.
    from stock_trading_system.utils.timez import utc_iso_z
    return utc_iso_z()


def _resolve_db_path(db_path: str | None) -> str:
    if db_path:
        return db_path
    try:
        from stock_trading_system.config import get_config
        return get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
    except Exception:
        return "data/portfolio.db"


def _resolve_user_id(db_path: str, task_id: str) -> int | str | None:
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT created_by FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def persist_event(
    task_id: str,
    event: str,
    payload: dict,
    *,
    db_path: str | None = None,
    user_id: int | str | None = None,
) -> dict | None:
    """Persist an event to task_events without broadcasting.

    Returns the envelope so the caller can hand it to whatever transport it
    likes (SocketIO, in-memory recorder, ...). Best-effort: returns None when
    we can't resolve user_id or the table doesn't exist yet.
    """
    db_path = _resolve_db_path(db_path)
    if user_id is None:
        user_id = _resolve_user_id(db_path, task_id)
    if user_id is None:
        logger.debug("Cannot resolve user_id for task %s, skipping persist", task_id)
        return None

    emitted_at = _now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False)
    seq = _persist_with_seq_retry(
        db_path, task_id, user_id, event, payload_json, emitted_at,
    )
    if seq is None:
        # Persist gave up (table missing, hard error, or contention >
        # _SEQ_RETRY_LIMIT). Don't crash the worker — best-effort.
        return None

    return {
        "task_id": task_id,
        "user_id": user_id,
        "seq": seq,
        "event": event,
        "payload": payload,
        "emitted_at": emitted_at,
    }


def _persist_with_seq_retry(
    db_path: str,
    task_id: str,
    user_id: int | str,
    event: str,
    payload_json: str,
    emitted_at: str,
) -> int | None:
    """Allocate the next seq from the DB and INSERT in one logical step.

    Two threads racing on the same task_id can both read the same
    MAX(seq) and write the same proposed seq+1; the UNIQUE(task_id,
    seq) constraint guarantees exactly one of them wins. The loser
    catches IntegrityError and retries with a fresh MAX(seq).
    """
    for _attempt in range(_SEQ_RETRY_LIMIT):
        try:
            conn = sqlite3.connect(db_path, timeout=10)
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM task_events "
                    "WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                seq = (row[0] if row and row[0] is not None else 0) + 1
                conn.execute(
                    "INSERT INTO task_events "
                    "(task_id, user_id, seq, event, payload, emitted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, user_id, seq, event, payload_json, emitted_at),
                )
                conn.commit()
                return seq
            finally:
                conn.close()
        except sqlite3.IntegrityError:
            # Lost the seq race — another writer grabbed this number.
            # Loop and retry with a freshly-computed MAX.
            continue
        except sqlite3.OperationalError as e:
            # Includes "no such table" (pre-migration) and "database is
            # locked" — log + give up so the worker doesn't crash on
            # progress events.
            logger.debug("task_events persist op-error: %s", e)
            return None
        except Exception as e:  # noqa: BLE001
            logger.debug("task_events persist failed: %s", e)
            return None
    logger.warning(
        "task_events seq allocation gave up after %d retries (task=%s)",
        _SEQ_RETRY_LIMIT, task_id,
    )
    return None


def emit_event(
    task_id: str,
    event: str,
    payload: dict,
    *,
    db_path: str | None = None,
    user_id: int | str | None = None,
    socketio=None,
) -> dict | None:
    """Unified event emission: persist + broadcast to user room.

    The broadcast goes to `user:{user_id}` so users only see their own events.
    For lifecycle events emitted from TaskManager we already broadcast on the
    injected socketio at the call site; this path keeps backward compatibility
    for worker progress events that don't have a TaskManager handle.
    """
    db_path = _resolve_db_path(db_path)
    if user_id is None:
        user_id = _resolve_user_id(db_path, task_id)
    envelope = persist_event(
        task_id, event, payload, db_path=db_path, user_id=user_id,
    )
    if envelope is None:
        return None

    # Resolve socketio if not provided. Avoid importing the web app module at
    # import-time (would create a cycle); only reach for it when actually
    # broadcasting.
    if socketio is None:
        try:
            from stock_trading_system.web.app import socketio as _sio
            socketio = _sio
        except Exception:
            pass

    if socketio is not None:
        try:
            socketio.emit(event, envelope, to=f"user:{envelope['user_id']}")
        except Exception as e:
            logger.debug("Failed to emit via socketio: %s", e)

    return envelope


def get_events_since(db_path: str, task_id: str, user_id: int, since_seq: int) -> list[dict]:
    """Fetch events for catch-up after reconnect."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, user_id, seq, event, payload, emitted_at "
            "FROM task_events "
            "WHERE task_id = ? AND user_id = ? AND seq > ? "
            "ORDER BY seq",
            (task_id, user_id, since_seq),
        ).fetchall()
        conn.close()
        return [
            {
                "task_id": r["task_id"],
                "user_id": r["user_id"],
                "seq": r["seq"],
                "event": r["event"],
                "payload": json.loads(r["payload"]),
                "emitted_at": r["emitted_at"],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("get_events_since failed: %s", e)
        return []
