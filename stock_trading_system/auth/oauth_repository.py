"""OAuth account storage — N:1 mapping to users.

Each row records a verified link between a (provider, provider_user_id) pair
and an internal user. Tokens are stored encrypted via oauth_crypto so a DB
leak alone never yields usable provider credentials.

The repository never creates users on its own — that path remains gated by
`_invite_mgr.validate/redeem` in the route layer. `upsert()` is invoked
only after the caller has resolved (or just minted) the target user_id.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from stock_trading_system.utils.timez import now_local
from typing import Optional

from stock_trading_system.auth.oauth_crypto import encrypt_token
from stock_trading_system.utils import get_logger

logger = get_logger("auth.oauth_repository")


@dataclass(frozen=True)
class OAuthAccount:
    id: int
    user_id: int
    provider: str
    provider_user_id: str
    email: Optional[str]
    email_verified: bool
    raw_profile_json: Optional[str]
    expires_at: Optional[str]
    created_at: str
    last_login_at: Optional[str]


@dataclass(frozen=True)
class OAuthProfileRecord:
    """Minimal subset of an OAuth provider profile that we persist."""
    sub: str
    email: Optional[str]
    email_verified: bool
    raw: dict


@dataclass(frozen=True)
class OAuthTokenRecord:
    """Tokens returned by a provider's token endpoint."""
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[str]


class OAuthAccountRepository:
    """SQLite-backed oauth_accounts storage."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_account(row: Optional[sqlite3.Row]) -> Optional[OAuthAccount]:
        if row is None:
            return None
        return OAuthAccount(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            provider_user_id=row["provider_user_id"],
            email=row["email"],
            email_verified=bool(row["email_verified"]),
            raw_profile_json=row["raw_profile_json"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    # ── Read ──────────────────────────────────────────────────────────

    def find_by_provider_id(
        self, provider: str, provider_user_id: str
    ) -> Optional[OAuthAccount]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM oauth_accounts "
                "WHERE provider = ? AND provider_user_id = ?",
                (provider, provider_user_id),
            ).fetchone()
            return self._row_to_account(row)

    def list_by_user(self, user_id: int) -> list[OAuthAccount]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM oauth_accounts WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
            return [acct for acct in (self._row_to_account(r) for r in rows) if acct]

    # ── Write ─────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        user_id: int,
        provider: str,
        profile: OAuthProfileRecord,
        tokens: OAuthTokenRecord,
    ) -> OAuthAccount:
        """Insert or update on (provider, provider_user_id).

        Always updates last_login_at on touch — the route layer relies on
        that to surface "last sign-in" timestamps in /settings.
        """
        now = now_local().strftime("%Y-%m-%d %H:%M:%S")
        access_enc = encrypt_token(tokens.access_token)
        refresh_enc = encrypt_token(tokens.refresh_token) if tokens.refresh_token else None
        raw_json = json.dumps(profile.raw, ensure_ascii=False)
        email_verified_int = 1 if profile.email_verified else 0

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM oauth_accounts "
                "WHERE provider = ? AND provider_user_id = ?",
                (provider, profile.sub),
            ).fetchone()

            if existing is not None:
                conn.execute(
                    """UPDATE oauth_accounts SET
                           email = ?,
                           email_verified = ?,
                           raw_profile_json = ?,
                           access_token_enc = ?,
                           refresh_token_enc = ?,
                           expires_at = ?,
                           last_login_at = ?
                       WHERE id = ?""",
                    (
                        profile.email,
                        email_verified_int,
                        raw_json,
                        access_enc,
                        refresh_enc,
                        tokens.expires_at,
                        now,
                        existing["id"],
                    ),
                )
                acct_id = existing["id"]
            else:
                cur = conn.execute(
                    """INSERT INTO oauth_accounts (
                           user_id, provider, provider_user_id, email,
                           email_verified, raw_profile_json,
                           access_token_enc, refresh_token_enc,
                           expires_at, last_login_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        provider,
                        profile.sub,
                        profile.email,
                        email_verified_int,
                        raw_json,
                        access_enc,
                        refresh_enc,
                        tokens.expires_at,
                        now,
                    ),
                )
                acct_id = cur.lastrowid

            row = conn.execute(
                "SELECT * FROM oauth_accounts WHERE id = ?", (acct_id,)
            ).fetchone()

        acct = self._row_to_account(row)
        if acct is None:
            # Should be impossible: we just wrote the row inside the same
            # transaction. Surface loudly rather than swallow.
            raise RuntimeError(
                f"oauth_accounts upsert produced no row (id={acct_id})"
            )
        logger.info(
            "oauth_accounts upsert provider=%s user_id=%d sub=%s",
            provider, user_id, profile.sub,
        )
        return acct

    def delete_by_user_provider(self, user_id: int, provider: str) -> bool:
        """Unlink a provider for a user. Returns True if a row was removed."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM oauth_accounts WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            )
            removed = cur.rowcount > 0
        if removed:
            logger.info("oauth_accounts unlinked user_id=%d provider=%s",
                        user_id, provider)
        return removed
