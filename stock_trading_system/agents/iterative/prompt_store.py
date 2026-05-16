"""Prompt version store — DB-backed management of agent prompt overrides.

Each prompt version goes through a lifecycle:
    candidate → testing (A/B) → active | retired

Only one version per agent_id can be ``active`` at a time.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_utc
from typing import Any

from stock_trading_system.utils import get_logger

logger = get_logger("iterative.prompt_store")


class PromptStore:
    """CRUD for the ``prompt_versions`` table."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Create ────────────────────────────────────────────────────────

    def save_version(
        self,
        agent_id: str,
        prompt_text: str,
        prompt_type: str = "system_prompt",
        source: str = "meta_agent",
        reasoning: str | None = None,
    ) -> int:
        """Insert a new prompt version (status=candidate). Returns its id."""
        now = now_utc().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO prompt_versions
                   (agent_id, prompt_text, prompt_type, source, reasoning,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'candidate', ?)""",
                (agent_id, prompt_text, prompt_type, source, reasoning, now),
            )
            version_id = int(cur.lastrowid)
        logger.info("Saved prompt version %d for %s (source=%s)", version_id, agent_id, source)
        return version_id

    # ── Read ──────────────────────────────────────────────────────────

    def get_version(self, version_id: int) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_versions WHERE id = ?", (version_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_active_prompt(self, agent_id: str) -> dict | None:
        """Return the currently active prompt for an agent, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM prompt_versions
                   WHERE agent_id = ? AND status = 'active'
                   ORDER BY id DESC LIMIT 1""",
                (agent_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_all_active_prompts(self) -> dict[str, dict]:
        """Return {agent_id: prompt_dict} for every agent with an active override."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE status = 'active'"
            ).fetchall()
            return {row["agent_id"]: dict(row) for row in rows}

    def get_testing_versions(self) -> list[dict]:
        """Return all versions currently in A/B testing."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE status = 'testing'"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_history(self, agent_id: str | None = None, limit: int = 20) -> list[dict]:
        with self._get_conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM prompt_versions WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prompt_versions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Update ────────────────────────────────────────────────────────

    def update_version(self, version_id: int, **fields: Any) -> None:
        """Update arbitrary columns on a prompt version row."""
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [version_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE prompt_versions SET {set_clause} WHERE id = ?",  # noqa: S608
                values,
            )

    def activate_version(self, version_id: int) -> None:
        """Set version to active and retire any previous active for same agent."""
        version = self.get_version(version_id)
        if not version:
            return
        with self._get_conn() as conn:
            # Retire any current active version for this agent
            conn.execute(
                """UPDATE prompt_versions SET status = 'retired'
                   WHERE agent_id = ? AND status = 'active'""",
                (version["agent_id"],),
            )
            conn.execute(
                "UPDATE prompt_versions SET status = 'active' WHERE id = ?",
                (version_id,),
            )
        logger.info("Activated prompt version %d for %s", version_id, version["agent_id"])

    def retire_version(self, version_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE prompt_versions SET status = 'retired' WHERE id = ?",
                (version_id,),
            )

    def start_testing(
        self, version_id: int, ab_session_id: int, baseline_session_id: int,
    ) -> None:
        """Transition a candidate version to testing with A/B session IDs."""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE prompt_versions
                   SET status = 'testing',
                       ab_session_id = ?,
                       baseline_session_id = ?
                   WHERE id = ?""",
                (ab_session_id, baseline_session_id, version_id),
            )
