"""Settings API contract tests.

The dotted-path schema between SettingsPage.tsx and config/settings.py is
load-bearing for both UX (clear-key button) and security (no foot-gun where
a routine save wipes a credential). These tests pin the contract:

    * GET /api/settings returns masked snapshot with `api_key_masked`.
    * POST /api/settings with `{provider.api_key: ""}` *does* clear.
    * Subsequent GET shows the cleared key as empty masked string.
    * POST without the api_key path leaves the saved key untouched.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def alice(app_client, monkeypatch):
    """Admin-logged client (fixture name kept for diff brevity).

    /api/settings GET+POST is admin-only as of hardening-iteration-v1 P0.2
    + mobile-ui-v1.3.1 addendum #3 — previously any logged-in user could
    rewrite the global config and steal LLM API keys (C3). Non-admin
    denial is owned by tests/web/test_settings_admin_gate.py. We drop
    the API-key env vars so file persistence is actually exercised —
    env-var overrides would shadow the YAML write."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    # Reload config so the unset env vars don't carry over from a prior load.
    import importlib
    from stock_trading_system.config import settings as _s
    importlib.reload(_s)
    from stock_trading_system import config as _c
    importlib.reload(_c)
    from stock_trading_system.config import load_config, get_config
    load_config()
    cfg = get_config()
    cfg["portfolio"] = {"db_path": app_client["db_path"]}
    cfg.setdefault("gemini", {})["api_key"] = ""
    cfg.setdefault("qwen", {})
    cfg["qwen"]["api_key"] = ""
    cfg["qwen"]["enabled"] = True

    users = app_client["users"]
    return app_client["make_client"](users.admin_email, users.admin_password)


def test_save_then_clear_gemini_key(alice):
    """Round-trip: save a key, see it masked, then clear via empty string."""
    # 1. Save a real-looking key
    rv = alice.post("/api/settings", json={"gemini.api_key": "AIza-real-test-key"})
    assert rv.status_code == 200, rv.get_json()
    assert "gemini.api_key" in (rv.get_json().get("applied") or [])

    # 2. GET shows it masked (last 4 chars visible per _mask_secret)
    rv = alice.get("/api/settings")
    body = rv.get_json()
    assert body["gemini"]["api_key_masked"], "expected masked key after save"
    assert body["gemini"]["api_key_masked"].endswith("-key")

    # 3. Clear via explicit empty string
    rv = alice.post("/api/settings", json={"gemini.api_key": ""})
    assert rv.status_code == 200, rv.get_json()
    assert "gemini.api_key" in (rv.get_json().get("applied") or [])

    # 4. Subsequent GET shows the masked field as empty
    rv = alice.get("/api/settings")
    body = rv.get_json()
    assert body["gemini"]["api_key_masked"] == "", \
        f"expected empty masked key after clear, got {body['gemini']['api_key_masked']!r}"


def test_save_other_field_does_not_touch_saved_api_key(alice):
    """A normal save without the api_key path must not wipe a stored key."""
    # Seed a key
    rv = alice.post("/api/settings", json={"gemini.api_key": "AIza-keep-me"})
    assert rv.status_code == 200

    # Save just the model — the frontend's normal save path drops api_key
    # entirely when the user didn't type into the field
    rv = alice.post("/api/settings", json={"gemini.model": "gemini-2.5-pro"})
    assert rv.status_code == 200

    # Key still present
    rv = alice.get("/api/settings")
    body = rv.get_json()
    assert body["gemini"]["api_key_masked"].endswith("p-me"), \
        f"key was wiped: {body['gemini']['api_key_masked']!r}"
    assert body["gemini"]["model"] == "gemini-2.5-pro"


def test_clear_qwen_key(alice):
    """Same path for qwen.api_key."""
    alice.post("/api/settings", json={"qwen.api_key": "sk-qwen-real-key"})
    body = alice.get("/api/settings").get_json()
    assert body["qwen"]["api_key_masked"], "expected masked qwen key after save"

    alice.post("/api/settings", json={"qwen.api_key": ""})
    body = alice.get("/api/settings").get_json()
    assert body["qwen"]["api_key_masked"] == ""


def test_anonymous_cannot_save_settings(app_client):
    anon = app_client["make_client"]()
    rv = anon.post("/api/settings", json={"gemini.api_key": ""})
    assert rv.status_code == 401
