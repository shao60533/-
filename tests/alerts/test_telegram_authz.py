"""Tests for hardening-iteration-v1 P1.1 [C2] Telegram bot whitelist.

Covers:
    - _init_authz: empty user_map → 0 + warning
    - _init_authz: valid email → chat_id in cache
    - _init_authz: missing/inactive user → not in cache + error log
    - _init_authz: malformed chat_id / email → skipped
    - _resolve_user_id: returns user_id or None
    - require_auth: rejects unauthorized chat (reply + no handler call)
    - require_auth: runs handler with user_id injected for authorized chat
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_trading_system.alerts import telegram_bot


def _bootstrap_db(path: Path) -> None:
    """Minimal users table — same shape as conftest._bootstrap_users_db
    but lighter (this test doesn't go through Flask)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            display_name  TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'user',
            status        TEXT    NOT NULL DEFAULT 'active',
            created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT,
            password_reset_token      TEXT,
            password_reset_expires_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _seed_users(db_path: Path, users: list[tuple[str, str]]) -> dict[str, int]:
    """Insert (email, role) pairs and return {email: id}."""
    from stock_trading_system.auth.repository import UserRepository
    repo = UserRepository(str(db_path))
    ids: dict[str, int] = {}
    for email, role in users:
        u = repo.create(email, "TestPass1!", role=role)
        ids[email] = u.id
    return ids


@pytest.fixture
def authz_env(tmp_path):
    """Tear up: DB with alice/bob, clean module-level cache."""
    db = tmp_path / "portfolio.db"
    _bootstrap_db(db)
    ids = _seed_users(db, [("alice@test.local", "user"),
                           ("bob@test.local", "user")])
    telegram_bot._chat_to_user = {}
    yield {"db": db, "ids": ids}
    telegram_bot._chat_to_user = {}


# ── _init_authz ────────────────────────────────────────────────────────────


def test_init_authz_empty_user_map_returns_zero(authz_env, caplog):
    config = {
        "portfolio": {"db_path": str(authz_env["db"])},
        "alerts": {"telegram": {"user_map": {}}},
    }
    with caplog.at_level("WARNING"):
        n = telegram_bot._init_authz(config)
    assert n == 0
    assert telegram_bot._chat_to_user == {}
    assert any("EMPTY user_map" in r.message for r in caplog.records)


def test_init_authz_resolves_valid_email(authz_env):
    config = {
        "portfolio": {"db_path": str(authz_env["db"])},
        "alerts": {"telegram": {"user_map": {
            "12345": "alice@test.local",
            67890: "bob@test.local",
        }}},
    }
    n = telegram_bot._init_authz(config)
    assert n == 2
    assert telegram_bot._chat_to_user[12345] == authz_env["ids"]["alice@test.local"]
    assert telegram_bot._chat_to_user[67890] == authz_env["ids"]["bob@test.local"]


def test_init_authz_skips_unknown_email(authz_env, caplog):
    config = {
        "portfolio": {"db_path": str(authz_env["db"])},
        "alerts": {"telegram": {"user_map": {
            "111": "alice@test.local",
            "222": "ghost@nowhere.local",  # not in users table
        }}},
    }
    with caplog.at_level("ERROR"):
        n = telegram_bot._init_authz(config)
    assert n == 1
    assert 111 in telegram_bot._chat_to_user
    assert 222 not in telegram_bot._chat_to_user
    assert any("no active user found" in r.message for r in caplog.records)


def test_init_authz_skips_invalid_chat_id(authz_env, caplog):
    config = {
        "portfolio": {"db_path": str(authz_env["db"])},
        "alerts": {"telegram": {"user_map": {
            "not-an-int": "alice@test.local",
            "999": "alice@test.local",
        }}},
    }
    with caplog.at_level("ERROR"):
        n = telegram_bot._init_authz(config)
    assert n == 1
    assert 999 in telegram_bot._chat_to_user
    assert any("Invalid Telegram chat_id" in r.message for r in caplog.records)


def test_init_authz_skips_empty_email(authz_env):
    config = {
        "portfolio": {"db_path": str(authz_env["db"])},
        "alerts": {"telegram": {"user_map": {
            "1": "",
            "2": "   ",
            "3": None,
            "4": "alice@test.local",
        }}},
    }
    n = telegram_bot._init_authz(config)
    assert n == 1
    assert 4 in telegram_bot._chat_to_user


# ── _resolve_user_id ───────────────────────────────────────────────────────


def test_resolve_user_id_returns_id_for_known_chat(authz_env):
    telegram_bot._chat_to_user = {42: 7}
    assert telegram_bot._resolve_user_id(42) == 7
    assert telegram_bot._resolve_user_id("42") == 7  # int coerced


def test_resolve_user_id_returns_none_for_unknown_chat(authz_env):
    telegram_bot._chat_to_user = {42: 7}
    assert telegram_bot._resolve_user_id(99) is None


# ── require_auth decorator ─────────────────────────────────────────────────


def _make_update(chat_id: int, text: str = "/test") -> MagicMock:
    """Minimal Update mock with reply_text awaitable."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.username = "test_user"
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context() -> MagicMock:
    context = MagicMock()
    context.user_data = {}
    return context


def test_require_auth_rejects_unauthorized(authz_env, caplog):
    telegram_bot._chat_to_user = {1: 100}
    inner = AsyncMock()
    wrapped = telegram_bot.require_auth(inner)

    update = _make_update(chat_id=999)
    context = _make_context()

    with caplog.at_level("WARNING"):
        asyncio.run(wrapped(update, context))

    inner.assert_not_called()
    update.message.reply_text.assert_awaited_once()
    args, _ = update.message.reply_text.call_args
    assert "未授权" in args[0]
    assert "user_id" not in context.user_data
    assert any("Unauthorized Telegram command" in r.message for r in caplog.records)


def test_require_auth_runs_handler_for_authorized(authz_env):
    telegram_bot._chat_to_user = {42: 100}
    inner = AsyncMock()
    wrapped = telegram_bot.require_auth(inner)

    update = _make_update(chat_id=42)
    context = _make_context()

    asyncio.run(wrapped(update, context))

    inner.assert_awaited_once_with(update, context)
    update.message.reply_text.assert_not_called()
    assert context.user_data["user_id"] == 100
