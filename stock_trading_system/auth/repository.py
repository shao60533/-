"""User repository — CRUD for the users table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_utc
from typing import Optional

from stock_trading_system.auth.password import hash_password
from stock_trading_system.utils import get_logger

logger = get_logger("auth.repository")


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    display_name: str
    role: str  # "admin" | "user"
    status: str  # "active" | "deleted"
    created_at: str
    last_login_at: Optional[str] = None
    password_reset_token: Optional[str] = None
    password_reset_expires_at: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class UserRepository:
    """SQLite-backed user storage."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_user(self, row) -> User | None:
        if row is None:
            return None
        return User(**dict(row))

    # ── Read ──────────────────────────────────────────────────────────

    def find_by_id(self, user_id: int) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()
            return self._row_to_user(row)

    def find_by_email(self, email: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? AND status = 'active'",
                (email.strip().lower(),),
            ).fetchone()
            return self._row_to_user(row)

    def find_by_reset_token(self, token: str) -> User | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE password_reset_token = ? AND status = 'active'",
                (token,),
            ).fetchone()
            return self._row_to_user(row)

    def list_all(self) -> list[User]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()
            return [self._row_to_user(r) for r in rows]

    def list_active(self) -> list[User]:
        """Active users only — what the scheduler / backfill iterate over."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE status = 'active' ORDER BY id ASC"
            ).fetchall()
            return [self._row_to_user(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0]

    # ── Write ─────────────────────────────────────────────────────────

    def create(
        self, email: str, password: str, display_name: str | None = None,
        role: str = "user",
    ) -> User:
        email_norm = email.strip().lower()
        name = display_name or email_norm.split("@")[0]
        pwd_hash = hash_password(password)
        now = now_utc().strftime("%Y-%m-%d %H:%M:%S")

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO users (email, password_hash, display_name, role, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (email_norm, pwd_hash, name, role, now),
            )
            user_id = cur.lastrowid

        return self.find_by_id(user_id)  # type: ignore[return-value]

    def update_last_login(self, user_id: int) -> None:
        now = now_utc().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, user_id),
            )

    def update_password(self, user_id: int, new_password: str) -> None:
        pwd_hash = hash_password(new_password)
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, password_reset_token = NULL, "
                "password_reset_expires_at = NULL WHERE id = ?",
                (pwd_hash, user_id),
            )

    def set_reset_token(self, user_id: int, token: str, expires_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET password_reset_token = ?, password_reset_expires_at = ? WHERE id = ?",
                (token, expires_at, user_id),
            )

    def soft_delete(self, user_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET status = 'deleted' WHERE id = ?",
                (user_id,),
            )
