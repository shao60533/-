"""TC-MS-A1 ~ A10: LLM provider API tests.

Run against an authenticated Flask test client backed by a temp DB and a
temp ``STOCK_CONFIG_DIR`` so we never touch the developer's real config.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app_client, monkeypatch):
    """Logged-in alice client with both Qwen and Gemini API keys configured."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


# ── TC-MS-A1: GET returns current provider + key status ──────────


def test_get_returns_state(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.get("/api/settings/llm-provider")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] in ("qwen", "gemini")
    assert body["has_qwen_key"] is True
    assert body["has_gemini_key"] is True
    assert body["locked_by_env"] is False


# ── TC-MS-A2: GET with env lock → locked_by_env=True ─────────────


def test_get_locked(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    resp = client.get("/api/settings/llm-provider")
    body = resp.get_json()
    assert body["locked_by_env"] is True
    assert body["active"] == "qwen"


# ── TC-MS-A3: POST valid switch ──────────────────────────────────


def test_post_valid_switch(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "gemini"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] == "gemini"


def test_post_resets_analyzer_singleton(client, monkeypatch):
    """After switching, the lazy analyzer singleton must be cleared."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from stock_trading_system.web import app as app_module
    # Force the analyzer to be set so we can verify it gets reset.
    app_module._analyzer = object()
    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "gemini"})
    assert resp.status_code == 200
    assert app_module._analyzer is None


# ── TC-MS-A4: POST invalid provider → 400 ────────────────────────


def test_post_invalid_provider(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "claude"})
    assert resp.status_code == 400
    assert resp.get_json()["reason"] == "invalid_provider"


# ── TC-MS-A5: POST target missing key → 400 ──────────────────────


def test_post_missing_key(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["gemini"]["api_key"] = ""  # remove gemini key

    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "gemini"})
    assert resp.status_code == 400
    assert resp.get_json()["reason"] == "missing_api_key"


# ── TC-MS-A6: POST env locked → 409 ──────────────────────────────


def test_post_locked(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "gemini"})
    assert resp.status_code == 409
    assert resp.get_json()["reason"] == "locked_by_env"


# ── TC-MS-A7: POST empty body → 400 ──────────────────────────────


def test_post_empty_body(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.post("/api/settings/llm-provider",
                       data="", content_type="application/json")
    assert resp.status_code == 400


# ── TC-MS-A8: POST missing provider field → 400 ──────────────────


def test_post_missing_field(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.post("/api/settings/llm-provider", json={})
    assert resp.status_code == 400


# ── TC-MS-A9: POST mixed case → success ──────────────────────────


def test_post_case_insensitive(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = client.post("/api/settings/llm-provider",
                       json={"provider": "GEMINI"})
    assert resp.status_code == 200
    assert resp.get_json()["active"] == "gemini"


# ── TC-MS-A10: consecutive switches ──────────────────────────────


def test_consecutive_switches(client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    r1 = client.post("/api/settings/llm-provider", json={"provider": "gemini"})
    assert r1.status_code == 200

    r2 = client.post("/api/settings/llm-provider", json={"provider": "qwen"})
    assert r2.status_code == 200
    assert r2.get_json()["active"] == "qwen"

    # Verify current state
    r3 = client.get("/api/settings/llm-provider")
    assert r3.get_json()["active"] == "qwen"


# ── Anonymous calls must be denied ───────────────────────────────


def test_anonymous_get_redirects_or_401(app_client):
    anon = app_client["make_client"]()
    resp = anon.get("/api/settings/llm-provider")
    assert resp.status_code == 401


def test_anonymous_post_denied(app_client):
    anon = app_client["make_client"]()
    resp = anon.post("/api/settings/llm-provider", json={"provider": "qwen"})
    assert resp.status_code == 401
