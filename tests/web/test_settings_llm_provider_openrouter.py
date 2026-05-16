"""LLM provider three-state — openrouter coverage.

docs/design/llm-openrouter.md v1.0 §8.5 — 3 cases focused on the OR
extensions to /api/settings/llm-provider GET/POST.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app_client, monkeypatch):
    """Logged-in alice client. We don't preload OR yaml — tests poke env
    or use the dedicated POST to set up the state they need."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    users = app_client["users"]
    # mobile-ui-v1.3.1 addendum #3 — /api/settings/llm-provider is now
    # admin-only; use the admin user to preserve test intent (covers the
    # provider+OR surface contract; non-admin denial is tested in
    # tests/web/test_settings_admin_gate.py).
    return app_client["make_client"](users.admin_email, users.admin_password)


# ── §8.5 TC1: GET surfaces has_openrouter_key alongside qwen/gemini ──


def test_get_surfaces_has_openrouter_key(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    resp = client.get("/api/settings/llm-provider")
    assert resp.status_code == 200
    body = resp.get_json()
    # Tri-state key flags all present (False is acceptable; the test
    # verifies the contract surface, not the conftest fixture state).
    assert "has_qwen_key" in body
    assert "has_gemini_key" in body
    assert "has_openrouter_key" in body
    assert isinstance(body["has_openrouter_key"], bool)


def test_get_has_openrouter_key_lights_up_under_env(client, monkeypatch):
    """OPENROUTER_API_KEY env should flip has_openrouter_key True even
    with empty yaml (cloud one-env activation)."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")
    resp = client.get("/api/settings/llm-provider")
    assert resp.get_json()["has_openrouter_key"] is True


# ── §8.5 TC2: POST openrouter without key → missing_api_key + zh msg ──


def test_post_openrouter_without_key_returns_missing_api_key(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    resp = client.post(
        "/api/settings/llm-provider",
        json={"provider": "openrouter"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["reason"] == "missing_api_key"
    # Error message uses the OR human label, not the literal id.
    assert "OpenRouter" in body["message"]


# ── §8.5 TC3: POST openrouter with env key succeeds + persists ───────


def test_post_openrouter_with_env_key_succeeds(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    resp = client.post(
        "/api/settings/llm-provider",
        json={"provider": "openrouter"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] == "openrouter"
    # Verify GET reads back the same active value
    follow = client.get("/api/settings/llm-provider").get_json()
    assert follow["active"] == "openrouter"
