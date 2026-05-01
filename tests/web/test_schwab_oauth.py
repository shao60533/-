"""Tests for Schwab OAuth web endpoints — fully mocked.

Covers:
  - /oauth/schwab/start: secret guard, missing config, redirect
  - /oauth/schwab/callback: state mismatch, success
  - /api/schwab/diagnose: secret guard, disabled provider, success
"""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.web import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("SCHWAB_APP_KEY", raising=False)
    monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
    monkeypatch.delenv("SCHWAB_OAUTH_SECRET", raising=False)
    monkeypatch.delenv("SCHWAB_CALLBACK_URL", raising=False)

    db_path = tmp_path / "portfolio.db"
    token_path = tmp_path / "schwab_token.json"

    for attr in (
        "_task_manager", "_task_store", "_local_cache",
        "_portfolio_mgr", "_alert_monitor", "_data_manager",
        "_analyzer", "_screener", "_report_gen", "_strategy_engine",
        "_scheduler", "_scheduler_thread", "_data_router",
    ):
        if hasattr(app_module, attr):
            setattr(app_module, attr, None)

    app = app_module.create_app()
    app.config["TESTING"] = True

    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["portfolio"] = {"db_path": str(db_path)}
    cfg["schwab"] = {
        "enabled": True,
        "app_key": "fake_key",
        "app_secret": "fake_secret",
        "callback_url": "https://example.com/oauth/schwab/callback",
        "oauth_secret": "magic",
        "token_path": str(token_path),
    }

    with app.test_client() as c:
        yield c

    tm = getattr(app_module, "_task_manager", None)
    if tm is not None:
        tm.shutdown()


# ── /oauth/schwab/start ─────────────────────────────────────────────


def test_start_rejects_without_secret(client):
    resp = client.get("/oauth/schwab/start")
    assert resp.status_code == 403


def test_start_rejects_wrong_secret(client):
    resp = client.get("/oauth/schwab/start?secret=wrong")
    assert resp.status_code == 403


def test_start_500_when_app_key_missing(client):
    from stock_trading_system.config import get_config
    get_config()["schwab"]["app_key"] = ""
    resp = client.get("/oauth/schwab/start?secret=magic")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "SCHWAB_APP_KEY" in body["missing"]


def test_start_redirects_to_schwab(client):
    Ctx = namedtuple("AuthContext",
                      ["callback_url", "authorization_url", "state"])
    fake_ctx = Ctx(
        callback_url="https://example.com/oauth/schwab/callback",
        authorization_url="https://api.schwabapi.com/v1/oauth/authorize?x=1",
        state="abc123",
    )
    with patch("schwab.auth.get_auth_context", return_value=fake_ctx):
        resp = client.get("/oauth/schwab/start?secret=magic",
                           follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("https://api.schwabapi.com")


# ── /oauth/schwab/callback ──────────────────────────────────────────


def test_callback_rejects_state_mismatch(client):
    # No prior session state → state_mismatch
    resp = client.get("/oauth/schwab/callback?code=xxx&state=evil")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "state_mismatch"


def test_callback_succeeds_after_start(client, tmp_path):
    Ctx = namedtuple("AuthContext",
                      ["callback_url", "authorization_url", "state"])
    fake_ctx = Ctx(
        callback_url="https://example.com/oauth/schwab/callback",
        authorization_url="https://api.schwabapi.com/v1/oauth/authorize?x=1",
        state="state-xyz",
    )

    # Simulate /start to populate session
    with patch("schwab.auth.get_auth_context", return_value=fake_ctx):
        client.get("/oauth/schwab/start?secret=magic", follow_redirects=False)

    # Simulate callback — token write happens via the writer callback
    def _fake_exchange(*args, **kwargs):
        kwargs["token_write_func"]({"access_token": "TKN"})
        return MagicMock()

    with patch("schwab.auth.client_from_received_url",
                side_effect=_fake_exchange):
        resp = client.get(
            "/oauth/schwab/callback?code=abc&state=state-xyz",
            follow_redirects=False,
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    # Token file actually written
    token_file = body["token_path"]
    import json as _json
    with open(token_file) as f:
        assert _json.load(f) == {"access_token": "TKN"}


# ── /api/schwab/diagnose ───────────────────────────────────────────


def test_diagnose_rejects_without_secret(client):
    resp = client.get("/api/schwab/diagnose")
    assert resp.status_code == 403


def test_diagnose_503_when_disabled(client):
    # No token file → SchwabProvider.enabled is False
    resp = client.get("/api/schwab/diagnose?secret=magic")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["enabled"] is False
    assert "error" in body


def test_diagnose_runs_smoke_when_enabled(client, tmp_path, monkeypatch):
    # Pre-create token file so SchwabProvider.enabled=True
    token_path = tmp_path / "schwab_token.json"
    token_path.write_text('{"access_token": "fake"}')
    from stock_trading_system.config import get_config
    get_config()["schwab"]["token_path"] = str(token_path)

    # Patch the provider methods on the singleton to avoid real network
    fake_quote = {"ticker": "AAPL", "last": 150.0, "close": 149.0,
                   "source": "schwab"}
    fake_batch = {"AAPL": fake_quote, "TSLA": fake_quote, "NVDA": fake_quote,
                   "MSFT": fake_quote, "GOOG": fake_quote}
    import pandas as _pd
    fake_df = _pd.DataFrame({"close": [1, 2, 3]})

    with patch.object(
        app_module, "_get_data_manager",
        wraps=app_module._get_data_manager,
    ):
        # Force singleton reset
        app_module._data_manager = None
        # Build the dm and stub schwab provider
        dm = app_module._get_data_manager()
        sch = dm.get_schwab_provider()
        sch.get_stock_price = MagicMock(return_value=fake_quote)
        sch.get_stock_price_batch = MagicMock(return_value=fake_batch)
        sch.get_stock_history = MagicMock(return_value=fake_df)

        resp = client.get("/api/schwab/diagnose?secret=magic")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["enabled"] is True
    assert body["single_quote_ok"] is True
    assert body["batch_quote_count"] == 5
    assert body["history_ok"] is True
    assert body["history_bars"] == 3
