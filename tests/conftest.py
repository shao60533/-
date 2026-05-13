"""Shared pytest fixtures for the stock-trading-system test suite.

Two concerns this file solves once for all suites:

1. Tests must never read or write the developer's real ``~/.stock_trading``
   directory. Every test gets its own ``STOCK_CONFIG_DIR`` and isolated
   ``portfolio.db`` so we can't leak state between runs or between machines.
2. Business APIs require an authenticated user. Reusable fixtures here
   bootstrap a multi-tenant-ready DB, create canonical alice/bob/admin
   users, and yield logged-in Flask test clients.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest


# ── 1. Isolated config dir + DB ──────────────────────────────────────────────


def _reset_app_singletons() -> None:
    """Wipe lazy module-level singletons in stock_trading_system.web.app."""
    try:
        from stock_trading_system.web import app as app_module
    except Exception:
        return
    for attr in (
        "_task_manager", "_task_store", "_local_cache",
        "_portfolio_mgr", "_alert_monitor", "_data_manager",
        "_analyzer", "_screener", "_report_gen", "_strategy_engine",
        "_scheduler", "_scheduler_thread", "_paper_store",
        "_data_router", "_cleanup_scheduler",
    ):
        if hasattr(app_module, attr):
            setattr(app_module, attr, None)


def _bootstrap_users_db(db_path: str) -> None:
    """Create the multi-tenant tables that ensure_multi_tenant_ready() looks for.

    We don't run the full migration script; we just create the tables that
    the business code actually reads at request time. This is the minimal
    surface needed for `g.user` to populate after login.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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
        CREATE TABLE IF NOT EXISTS invite_codes (
            code        TEXT    PRIMARY KEY,
            created_by  INTEGER NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at  TEXT,
            used_by     INTEGER,
            used_at     TEXT,
            revoked_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id        INTEGER PRIMARY KEY,
            llm_provider   TEXT,
            notify_email   INTEGER DEFAULT 0,
            created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.close()


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    """Point STOCK_CONFIG_DIR at a fresh temp directory for the test.

    Reloads ``stock_trading_system.config.settings`` so the module-level
    ``_USER_CONFIG_DIR`` reflects the override. Without the reload the
    module captured the env value at first import.
    """
    cfg_dir = tmp_path / "stock_trading"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STOCK_CONFIG_DIR", str(cfg_dir))

    # Reload config.settings so module-level path constants pick up the env.
    from stock_trading_system.config import settings as _settings_mod
    importlib.reload(_settings_mod)
    # Re-export reloaded names through the package, since stock_trading_system.config
    # re-exports from settings.
    from stock_trading_system import config as _config_pkg
    importlib.reload(_config_pkg)
    # Ensure dependent modules see the reloaded names too.
    sys.modules["stock_trading_system.config.settings"] = _settings_mod
    sys.modules["stock_trading_system.config"] = _config_pkg
    return cfg_dir


# ── 2. Authenticated Flask test clients ──────────────────────────────────────


@pytest.fixture
def app_client(tmp_path, isolated_config_dir, monkeypatch):
    """Flask test client + a TestUsers handle with alice/bob/admin available.

    The fixture:
        * creates an isolated portfolio.db with users / invite_codes tables;
        * creates three canonical users (admin/alice/bob);
        * builds the Flask app pointing at this DB;
        * exposes a tiny helper for logging clients in/out.
    """
    db_path = tmp_path / "portfolio.db"
    _bootstrap_users_db(str(db_path))

    # Pre-create users so multi_tenant_ready returns True at app boot.
    from stock_trading_system.auth.repository import UserRepository
    repo = UserRepository(str(db_path))
    admin_user = repo.create("admin@test.local", "AdminPass1!", role="admin")
    alice_user = repo.create("alice@test.local", "AlicePass1!")
    bob_user = repo.create("bob@test.local", "BobPass1!")

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # Pin DB path via env so create_app's UserRepository / TaskManager / etc.
    # all bind to the same temp DB. Setting it AFTER app creation is too late
    # because create_app captures db_path from config before we can edit it.
    monkeypatch.setenv("STOCK_DB_PATH", str(db_path))
    # Default-off for the daily-snapshot scheduler in tests; suites that
    # explicitly verify the cron wiring should clear this env locally.
    monkeypatch.setenv("DISABLE_DAILY_SNAPSHOT_SCHEDULER", "1")
    # Pin API keys via env too so any code path that reloads the config (e.g.
    # the LLM-provider POST handler calls save_config → load_config) does not
    # blow away our in-memory test keys.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    _reset_app_singletons()

    from stock_trading_system.web import app as app_module
    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    # Disable rate-limiter for the shared suite — individual tests that
    # need to exercise the limit (e.g. tests/auth/test_rate_limit.py)
    # flip the flag back on locally.
    flask_app.config["RATELIMIT_ENABLED"] = False
    try:
        from stock_trading_system.web.app import limiter as _lim
        _lim.enabled = False
        _lim.reset()
        # Best-effort storage clear: MemoryStorage keeps counters in a
        # plain dict, so wiping it between fixtures stops cross-test
        # leakage when tests/auth/test_rate_limit.py flips enabled back on.
        try:
            _lim.storage.storage.clear()
        except Exception:
            pass
    except Exception:
        pass

    # Override the loaded config so all lazy singletons hit our temp DB.
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["portfolio"] = {"db_path": str(db_path)}
    cfg.setdefault("qwen", {})
    cfg["qwen"].update({
        "api_key": "sk-test", "model": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "enabled": True,
    })
    cfg.setdefault("gemini", {})
    cfg["gemini"].update({"api_key": "AIza-test", "model": "gemini-2.5-flash"})

    class TestUsers:
        admin_email, admin_password = "admin@test.local", "AdminPass1!"
        alice_email, alice_password = "alice@test.local", "AlicePass1!"
        bob_email, bob_password = "bob@test.local", "BobPass1!"
        admin = admin_user
        alice = alice_user
        bob = bob_user

    def login(client, email, password):
        rv = client.post("/api/auth/login",
                         json={"email": email, "password": password})
        assert rv.status_code == 200, f"login failed: {rv.get_json()}"
        return rv

    def make_client(email=None, password=None):
        c = flask_app.test_client()
        if email is not None:
            login(c, email, password)
        return c

    yield {
        "app": flask_app,
        "users": TestUsers(),
        "make_client": make_client,
        "login": login,
        "db_path": str(db_path),
    }

    # Drain the task manager BEFORE pytest closes stdout. The earlier
    # `shutdown(wait=False)` returned immediately, leaving worker threads
    # running; when they later tried to log they hit a closed file.
    #
    # Order:
    #   1. cancel_all() — signal cancel_event so cooperative workers exit.
    #   2. shutdown(wait=True, cancel_futures=True) — cancel anything still
    #      queued and block until in-flight work finishes its last log line.
    tm = getattr(app_module, "_task_manager", None)
    if tm is not None:
        try:
            tm.cancel_all()
        except Exception:
            pass
        try:
            tm.shutdown(wait=True, cancel_futures=True)
        except Exception:
            pass
    _reset_app_singletons()


@pytest.fixture
def alice_client(app_client):
    """Pre-logged-in client for the canonical 'alice' user."""
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


@pytest.fixture
def bob_client(app_client):
    users = app_client["users"]
    return app_client["make_client"](users.bob_email, users.bob_password)


@pytest.fixture
def admin_client(app_client):
    return app_client["make_client"](
        app_client["users"].admin_email,
        app_client["users"].admin_password,
    )


@pytest.fixture
def anon_client(app_client):
    return app_client["make_client"]()
