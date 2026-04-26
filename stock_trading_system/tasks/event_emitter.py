"""Unified event emission for all task workers.

emit_event() is the ONLY way workers should push progress to the frontend.
It persists events to task_events table (for catch-up on reconnect) and
broadcasts via SocketIO to the user's room (per-user isolation).

All events follow the standard envelope:
    {task_id, user_id, seq, event, payload, emitted_at}
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from stock_trading_system.utils import get_logger

logger = get_logger("tasks.event_emitter")

_seq_lock = threading.Lock()
_seq_cache: dict[str, int] = {}


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
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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

    with _seq_lock:
        seq = _seq_cache.get(task_id, 0) + 1
        _seq_cache[task_id] = seq

    emitted_at = _now_iso()
    envelope = {
        "task_id": task_id,
        "user_id": user_id,
        "seq": seq,
        "event": event,
        "payload": payload,
        "emitted_at": emitted_at,
    }

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO task_events (task_id, user_id, seq, event, payload, emitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, user_id, seq, event, json.dumps(payload, ensure_ascii=False), emitted_at),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Table might not exist yet (pre-migration) — don't crash the worker
        logger.debug("Failed to persist event: %s", e)

    return envelope


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
