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


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def emit_event(
    task_id: str,
    event: str,
    payload: dict,
    *,
    db_path: str | None = None,
    user_id: int | None = None,
    socketio=None,
) -> dict | None:
    """Unified event emission: persist + broadcast.

    Args:
        task_id: The task this event belongs to.
        event: Event type string (e.g. 'task_progress', 'guru_unit_done').
        payload: Event-specific data dict.
        db_path: Path to SQLite DB. If None, tries to resolve from config.
        user_id: Owner of the task. If None, looks up from tasks table.
        socketio: Flask-SocketIO instance. If None, tries to import from app.

    Returns:
        The envelope dict, or None on failure.
    """
    # Resolve db_path
    if db_path is None:
        try:
            from stock_trading_system.config import get_config
            db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        except Exception:
            db_path = "data/portfolio.db"

    # Resolve user_id from task record if not provided
    if user_id is None:
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT created_by FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            conn.close()
            user_id = row[0] if row else None
        except Exception:
            pass

    if user_id is None:
        logger.debug("Cannot resolve user_id for task %s, skipping emit", task_id)
        return None

    # Generate sequential seq number (per-task)
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

    # 1. Persist to task_events table
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

    # 2. Broadcast via SocketIO to user's room
    if socketio is None:
        try:
            from stock_trading_system.web.app import socketio as _sio
            socketio = _sio
        except Exception:
            pass

    if socketio is not None:
        try:
            socketio.emit(event, envelope, to=f"user:{user_id}")
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
