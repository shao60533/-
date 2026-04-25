"""Tests for auth module: password, repository, invite, session, decorators."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.auth.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from stock_trading_system.auth.repository import UserRepository
from stock_trading_system.auth.invite import InviteCodeManager
from stock_trading_system.auth.bootstrap import ensure_multi_tenant_ready


@pytest.fixture()
def db_path(tmp_path):
    """Create a DB with users + invite_codes tables."""
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT,
            password_reset_token TEXT,
            password_reset_expires_at TEXT
        );
        CREATE TABLE invite_codes (
            code TEXT PRIMARY KEY,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            used_by INTEGER,
            used_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE user_settings (
            user_id INTEGER PRIMARY KEY,
            llm_provider TEXT,
            notify_email INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()
    return path


# ═══════════════════════════════════════════════════════════════════
# Password
# ═══════════════════════════════════════════════════════════════════


class TestPassword:
    def test_hash_and_verify(self):
        hashed = hash_password("MyP@ss123")
        assert hashed.startswith("$2b$12$")
        assert verify_password("MyP@ss123", hashed)
        assert not verify_password("wrong", hashed)

    def test_validate_too_short(self):
        assert validate_password_strength("Abc1") is not None

    def test_validate_all_digits(self):
        assert validate_password_strength("12345678") is not None

    def test_validate_all_alpha(self):
        assert validate_password_strength("abcdefgh") is not None

    def test_validate_good(self):
        assert validate_password_strength("MyP@ss123") is None


# ═══════════════════════════════════════════════════════════════════
# Repository
# ═══════════════════════════════════════════════════════════════════


class TestUserRepository:
    def test_create_and_find(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("Admin@Test.COM", "Pass1234", "Admin")
        assert user.email == "admin@test.com"
        assert user.display_name == "Admin"
        assert user.role == "user"

        found = repo.find_by_email("admin@test.com")
        assert found is not None
        assert found.id == user.id

    def test_find_by_id(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("u@x.com", "Pass1234")
        found = repo.find_by_id(user.id)
        assert found is not None

    def test_soft_delete_hides_user(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("del@x.com", "Pass1234")
        repo.soft_delete(user.id)
        assert repo.find_by_id(user.id) is None
        assert repo.find_by_email("del@x.com") is None

    def test_update_password(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("pw@x.com", "OldPass1")
        repo.update_password(user.id, "NewPass2")
        updated = repo.find_by_id(user.id)
        assert verify_password("NewPass2", updated.password_hash)

    def test_email_uniqueness(self, db_path):
        repo = UserRepository(db_path)
        repo.create("dup@x.com", "Pass1234")
        with pytest.raises(Exception):
            repo.create("dup@x.com", "Pass5678")

    def test_display_name_defaults_to_email_prefix(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("hello@world.com", "Pass1234")
        assert user.display_name == "hello"

    def test_count(self, db_path):
        repo = UserRepository(db_path)
        assert repo.count() == 0
        repo.create("a@x.com", "Pass1234")
        repo.create("b@x.com", "Pass5678")
        assert repo.count() == 2

    def test_set_reset_token(self, db_path):
        repo = UserRepository(db_path)
        user = repo.create("reset@x.com", "Pass1234")
        repo.set_reset_token(user.id, "tok-123", "2099-12-31 23:59:59")
        found = repo.find_by_reset_token("tok-123")
        assert found is not None
        assert found.id == user.id


# ═══════════════════════════════════════════════════════════════════
# Invite
# ═══════════════════════════════════════════════════════════════════


class TestInviteCodeManager:
    def test_generate_and_validate(self, db_path):
        repo = UserRepository(db_path)
        admin = repo.create("admin@x.com", "Pass1234", role="admin")
        mgr = InviteCodeManager(db_path)
        code = mgr.generate(admin.id, expires_in_days=7)
        assert len(code) >= 8
        assert mgr.validate(code) is None  # valid

    def test_invalid_code(self, db_path):
        mgr = InviteCodeManager(db_path)
        assert mgr.validate("nonexistent") == "invite_invalid"

    def test_used_code(self, db_path):
        repo = UserRepository(db_path)
        admin = repo.create("admin@x.com", "Pass1234", role="admin")
        mgr = InviteCodeManager(db_path)
        code = mgr.generate(admin.id)
        mgr.redeem(code, admin.id)
        assert mgr.validate(code) == "invite_used"

    def test_revoked_code(self, db_path):
        repo = UserRepository(db_path)
        admin = repo.create("admin@x.com", "Pass1234", role="admin")
        mgr = InviteCodeManager(db_path)
        code = mgr.generate(admin.id)
        mgr.revoke(code)
        assert mgr.validate(code) == "invite_revoked"

    def test_expired_code(self, db_path):
        repo = UserRepository(db_path)
        admin = repo.create("admin@x.com", "Pass1234", role="admin")
        mgr = InviteCodeManager(db_path)
        code = mgr.generate(admin.id, expires_in_days=0)
        # Manually set expires_at to the past
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE invite_codes SET expires_at = '2020-01-01 00:00:00' WHERE code = ?",
            (code,),
        )
        conn.commit()
        conn.close()
        assert mgr.validate(code) == "invite_expired"

    def test_list_all(self, db_path):
        repo = UserRepository(db_path)
        admin = repo.create("admin@x.com", "Pass1234", role="admin")
        mgr = InviteCodeManager(db_path)
        mgr.generate(admin.id)
        mgr.generate(admin.id)
        assert len(mgr.list_all()) == 2


# ═══════════════════════════════════════════════════════════════════
# Bootstrap
# ═══════════════════════════════════════════════════════════════════


class TestBootstrap:
    def test_no_users_table(self, tmp_path):
        db = str(tmp_path / "empty.db")
        sqlite3.connect(db).close()
        assert ensure_multi_tenant_ready(db) is False

    def test_empty_users_table(self, db_path):
        assert ensure_multi_tenant_ready(db_path) is False

    def test_ready(self, db_path):
        repo = UserRepository(db_path)
        repo.create("admin@x.com", "Pass1234", role="admin")
        assert ensure_multi_tenant_ready(db_path) is True


# ═══════════════════════════════════════════════════════════════════
# Decorators
# ═══════════════════════════════════════════════════════════════════


class TestDecorators:
    def test_login_required_api_returns_401(self):
        from flask import Flask
        from stock_trading_system.auth.decorators import login_required

        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"

        @app.route("/api/test")
        @login_required
        def test_route():
            return "ok"

        with app.test_client() as client:
            resp = client.get("/api/test")
            assert resp.status_code == 401

    def test_admin_required_returns_403(self):
        from flask import Flask, g
        from stock_trading_system.auth.decorators import admin_required

        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"

        @app.before_request
        def set_no_user():
            g.user = None

        @app.route("/api/admin-test")
        @admin_required
        def admin_route():
            return "ok"

        with app.test_client() as client:
            resp = client.get("/api/admin-test")
            assert resp.status_code == 403
