"""P1-C fix verification — _reset_config_dependent_singletons recognizes
openrouter.* paths so analyzer cache busts on OR config changes.

Pre-fix: changing OR api_key / base_url / headers via /api/settings
POST would NOT clear the cached _analyzer; the running graph kept
using the stale config until a manual provider switch or process
restart. The matcher only checked ``gemini.`` / ``qwen.`` / ``llm``
prefixes.
"""

from __future__ import annotations

import pytest


def test_openrouter_path_busts_analyzer_singleton():
    """Direct unit test of the reset function — passing any
    'openrouter.*' path must clear ``_analyzer``."""
    from stock_trading_system.web import app as app_mod

    # Stub the analyzer slot so we can detect the reset.
    app_mod._analyzer = object()
    sentinel = app_mod._analyzer

    # Path-style update through dotted-path API
    app_mod._reset_config_dependent_singletons(["openrouter.api_key"])
    assert app_mod._analyzer is None, "openrouter.api_key should bust analyzer"

    # Restore + try base_url
    app_mod._analyzer = sentinel
    app_mod._reset_config_dependent_singletons(["openrouter.base_url"])
    assert app_mod._analyzer is None

    # Top-level openrouter path (e.g. from /openrouter/active POST)
    app_mod._analyzer = sentinel
    app_mod._reset_config_dependent_singletons(["openrouter.active"])
    assert app_mod._analyzer is None

    # Sanity: an unrelated path doesn't bust the analyzer.
    app_mod._analyzer = sentinel
    app_mod._reset_config_dependent_singletons(["alerts.email.smtp_host"])
    assert app_mod._analyzer is sentinel


def test_settings_post_openrouter_api_key_resets_analyzer(app_client, monkeypatch):
    """Functional: POST /api/settings with an openrouter.* field must
    end with _analyzer cleared."""
    from stock_trading_system.web import app as app_mod
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    users = app_client["users"]
    # /api/settings is admin-only (P0.2 / C3). The user-level alternative
    # /api/settings/openrouter/active is covered by the next test.
    client = app_client["make_client"](users.admin_email, users.admin_password)

    app_mod._analyzer = object()
    resp = client.post(
        "/api/settings",
        json={"openrouter.base_url": "https://or.example.com/api/v1"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert app_mod._analyzer is None, (
        "POST openrouter.base_url should reset the analyzer singleton"
    )


def test_openrouter_active_post_resets_analyzer(app_client, monkeypatch):
    """The /api/settings/openrouter/active POST must also reset the
    analyzer (preset swap = different deep/quick models)."""
    from stock_trading_system.web import app as app_mod
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    users = app_client["users"]
    client = app_client["make_client"](users.alice_email, users.alice_password)

    app_mod._analyzer = object()
    resp = client.post(
        "/api/settings/openrouter/active",
        json={"role": "deep", "preset_id": "gemini-3.1-pro"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert app_mod._analyzer is None
