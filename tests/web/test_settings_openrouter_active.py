"""OpenRouter preset switch endpoint.

docs/design/llm-openrouter.md v1.0 §9.1 — 4 cases for
/api/settings/openrouter/active GET/POST.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app_client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


# ── §9.1 TC1: GET requires login ─────────────────────────────────────


def test_get_active_requires_login(app_client):
    """Anonymous client (no logged-in user) → 401."""
    anon = app_client["make_client"]()
    resp = anon.get("/api/settings/openrouter/active")
    assert resp.status_code == 401


# ── §9.1 TC2: GET returns deep + quick + presets list ────────────────


def test_get_active_returns_resolved_presets(client):
    """Default yaml ships 3 presets — endpoint must surface them plus
    the deep/quick currently resolved by router (deepseek-v4-pro /
    deepseek-v4-flash by default)."""
    resp = client.get("/api/settings/openrouter/active")
    assert resp.status_code == 200
    body = resp.get_json()
    # Resolved deep + quick presets carry the full normalised shape.
    assert body["deep"]["model"] == "deepseek/deepseek-v4-pro"
    assert body["quick"]["model"] == "deepseek/deepseek-v4-flash"
    # Pool surfaces every yaml preset in declaration order.
    preset_ids = [p["id"] for p in body["presets"]]
    assert preset_ids == [
        "deepseek-v4-pro", "gemini-3.1-pro", "deepseek-v4-flash",
    ]
    # Active pointers are forwarded raw so the UI knows which to
    # highlight (these come from yaml, not from the resolver fallback).
    assert body["active"]["deep"] == "deepseek-v4-pro"
    assert body["active"]["quick"] == "deepseek-v4-flash"


# ── §9.1 TC3: POST swaps active.deep + persists ──────────────────────


def test_post_active_swaps_deep_pointer(client):
    """User picks gemini-3.1-pro for deep role. Persist + readback."""
    resp = client.post(
        "/api/settings/openrouter/active",
        json={"role": "deep", "preset_id": "gemini-3.1-pro"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["active"]["deep"] == "gemini-3.1-pro"
    # GET reads back the new active.deep — proves yaml persistence.
    follow = client.get("/api/settings/openrouter/active").get_json()
    assert follow["active"]["deep"] == "gemini-3.1-pro"
    # quick pointer untouched
    assert follow["active"]["quick"] == "deepseek-v4-flash"
    # ``deep`` resolution now uses the new preset
    assert follow["deep"]["id"] == "gemini-3.1-pro"
    assert follow["deep"]["model"] == "google/gemini-3.1-pro-preview"


# ── §9.1 TC4: POST validates role + preset_id ────────────────────────


def test_post_invalid_role_rejected(client):
    resp = client.post(
        "/api/settings/openrouter/active",
        json={"role": "garbage", "preset_id": "deepseek-v4-pro"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["reason"] == "invalid_role"


def test_post_unknown_preset_rejected(client):
    resp = client.post(
        "/api/settings/openrouter/active",
        json={"role": "deep", "preset_id": "does-not-exist"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["reason"] == "unknown_preset"
    assert "does-not-exist" in body["message"]


def test_post_locked_by_env_returns_409(client, monkeypatch):
    """LLM_PROVIDER env lock blocks preset switch too — same UI affordance
    as the provider switch (preset is a sub-axis of OR, not independent)."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    resp = client.post(
        "/api/settings/openrouter/active",
        json={"role": "deep", "preset_id": "gemini-3.1-pro"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["reason"] == "locked_by_env"
