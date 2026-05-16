"""User onboarding state storage.

Fail-soft on all writes — onboarding bookkeeping must never break the
business action that triggered it (register / portfolio.add / analysis
worker success / paper-trade plan save / etc).

State machine:

    register handler        → init_for_new_user(user_id)
                                welcome_pending=1, welcomed=0
    first dashboard visit   → frontend reads /api/onboarding/state
                                → sees welcome_pending=1 → shows modal
    user clicks Skip/Tour   → /api/onboarding/mark-welcomed
                                welcomed=1, welcome_pending=0
    business action success → mark_step("add-holding" | "first-analysis" |
                                        "first-screen" | "first-paper-plan")
    user closes checklist   → /api/onboarding/dismiss-checklist
    settings → reset        → /api/onboarding/reset
                                welcome_pending=1, everything else cleared
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from stock_trading_system.utils import get_logger

logger = get_logger("auth.onboarding_repository")


@dataclass
class OnboardingState:
    """Snapshot of one user's onboarding state."""

    user_id: int
    welcome_pending: bool = False
    welcomed: bool = False
    tour_completed: bool = False
    checklist_dismissed: bool = False
    tour_skipped_at_step: Optional[int] = None
    steps_completed: dict = field(default_factory=dict)
    updated_at: str = ""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class OnboardingRepository:
    """SQLite-backed onboarding state store."""

    KNOWN_STEPS = frozenset({
        "add-holding", "first-analysis", "first-screen", "first-paper-plan",
    })

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_state(row: sqlite3.Row | None, user_id: int) -> OnboardingState:
        if row is None:
            return OnboardingState(user_id=user_id)
        try:
            steps = json.loads(row["steps_completed"] or "{}")
            if not isinstance(steps, dict):
                steps = {}
        except (json.JSONDecodeError, TypeError):
            steps = {}
        return OnboardingState(
            user_id=row["user_id"],
            welcome_pending=bool(row["welcome_pending"]),
            welcomed=bool(row["welcomed"]),
            tour_completed=bool(row["tour_completed"]),
            checklist_dismissed=bool(row["checklist_dismissed"]),
            tour_skipped_at_step=row["tour_skipped_at_step"],
            steps_completed=steps,
            updated_at=row["updated_at"] or "",
        )

    # ── Reads ────────────────────────────────────────────────────────────

    def get_or_init(self, user_id: int) -> OnboardingState:
        """Return state for ``user_id``; create a default row if missing.

        Default row (``welcome_pending=0``) covers pre-existing users who
        existed before the migration shipped — they should NOT get the
        welcome modal. Only ``init_for_new_user`` flips welcome_pending=1.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_onboarding WHERE user_id=?", (user_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO user_onboarding (user_id) VALUES (?)", (user_id,),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM user_onboarding WHERE user_id=?", (user_id,),
                ).fetchone()
            return self._row_to_state(row, user_id)

    # ── Writes (all fail-soft) ───────────────────────────────────────────

    def init_for_new_user(self, user_id: int) -> None:
        """Called from register handlers. Sets welcome_pending=1.

        Fail-soft: write failure is logged but never raised — registration
        must not roll back because of an onboarding bookkeeping miss.
        """
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO user_onboarding (user_id, welcome_pending)
                       VALUES (?, 1)
                       ON CONFLICT(user_id) DO UPDATE SET welcome_pending=1,
                                                          updated_at=excluded.updated_at""",
                    (user_id,),
                )
                conn.commit()
        except Exception as e:
            logger.warning(
                "onboarding init_for_new_user failed user=%s: %s", user_id, e
            )

    def mark_step(self, user_id: int, step_id: str) -> bool:
        """Idempotent. Returns True iff a new step was actually marked.

        Returns False when:
          * ``step_id`` is not in ``KNOWN_STEPS``
          * the step was already True (idempotent no-op)
          * the DB write fails (fail-soft)
        """
        if step_id not in self.KNOWN_STEPS:
            return False
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT steps_completed FROM user_onboarding WHERE user_id=?",
                    (user_id,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO user_onboarding (user_id) VALUES (?)",
                        (user_id,),
                    )
                    steps: dict = {}
                else:
                    try:
                        steps = json.loads(row["steps_completed"] or "{}")
                        if not isinstance(steps, dict):
                            steps = {}
                    except (json.JSONDecodeError, TypeError):
                        steps = {}
                if steps.get(step_id):
                    return False
                steps[step_id] = True
                conn.execute(
                    """UPDATE user_onboarding
                       SET steps_completed=?, updated_at=?
                       WHERE user_id=?""",
                    (json.dumps(steps), _now(), user_id),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning(
                "onboarding mark_step failed user=%s step=%s: %s",
                user_id, step_id, e,
            )
            return False

    def mark_welcomed(self, user_id: int, *, tour_completed: bool = False) -> None:
        """Flip welcomed=1 (and tour_completed=1 if applicable).

        Always clears welcome_pending so the modal won't re-fire on the
        next page load.
        """
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """UPDATE user_onboarding
                       SET welcomed=1,
                           welcome_pending=0,
                           tour_completed=CASE WHEN ? THEN 1 ELSE tour_completed END,
                           updated_at=?
                       WHERE user_id=?""",
                    (1 if tour_completed else 0, _now(), user_id),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        """INSERT INTO user_onboarding
                              (user_id, welcomed, tour_completed,
                               welcome_pending, updated_at)
                           VALUES (?, 1, ?, 0, ?)""",
                        (user_id, 1 if tour_completed else 0, _now()),
                    )
                conn.commit()
        except Exception as e:
            logger.warning(
                "onboarding mark_welcomed failed user=%s: %s", user_id, e
            )

    def dismiss_checklist(self, user_id: int) -> None:
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """UPDATE user_onboarding
                       SET checklist_dismissed=1, updated_at=?
                       WHERE user_id=?""",
                    (_now(), user_id),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        """INSERT INTO user_onboarding
                              (user_id, checklist_dismissed, updated_at)
                           VALUES (?, 1, ?)""",
                        (user_id, _now()),
                    )
                conn.commit()
        except Exception as e:
            logger.warning(
                "onboarding dismiss_checklist failed user=%s: %s", user_id, e
            )

    def reset(self, user_id: int) -> None:
        """Clear all flags + steps; set ``welcome_pending=1`` so the modal
        re-fires on the next visit."""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """UPDATE user_onboarding
                       SET welcome_pending=1,
                           welcomed=0,
                           tour_completed=0,
                           checklist_dismissed=0,
                           tour_skipped_at_step=NULL,
                           steps_completed='{}',
                           updated_at=?
                       WHERE user_id=?""",
                    (_now(), user_id),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        """INSERT INTO user_onboarding
                              (user_id, welcome_pending, updated_at)
                           VALUES (?, 1, ?)""",
                        (user_id, _now()),
                    )
                conn.commit()
        except Exception as e:
            logger.warning(
                "onboarding reset failed user=%s: %s", user_id, e
            )
