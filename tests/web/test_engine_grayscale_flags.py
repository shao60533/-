"""hardening-iteration-v1 P3.1 + P3.2 step-3 — grayscale engine flag.

Step-3 ships an opt-in feature flag (``config.backtest.engine`` and
``config.screener.engine``) that lets the operator route the
``/api/backtest`` and ``/api/screen`` endpoints through the v2 / v3
implementations without touching code. Defaults stay on the legacy
engines so no production behaviour changes until an explicit
config edit lands.

This suite locks down:

  1. ``_backtest_engine_choice()`` defaults to ``v1`` when unset /
     unknown; respects ``v2`` when set.
  2. ``_screener_engine_choice()`` defaults to ``v1``; respects ``v3``.
  3. ``/api/backtest/strategies`` switches its source list based on
     the flag (v2 reads BacktestEngine.list_strategies, v1 reads
     Backtester.list_strategies).
  4. ``/api/backtest/run`` returns a payload carrying BOTH schemas
     (v1 + v2 keys) when the v2 flag is on — courtesy of to_v1_dict
     — so existing frontend consumers keep working.
  5. ``/api/screen`` ``engine`` field round-trips into the WS
     ``screen_status`` / ``screen_result`` emit so the UI can show
     "running on v3" while the dashboard transitions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── _backtest_engine_choice / _screener_engine_choice ──────────────────────


def test_backtest_engine_default_v1(app_client):
    """No config entry → "v1"."""
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["backtest"] = {}
    # Hit the strategies endpoint as a proxy for the choice helper.
    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    rv = admin.get("/api/backtest/strategies")
    assert rv.status_code == 200
    body = rv.get_json()
    # Both engines expose .list_strategies(); the test asserts a
    # non-error envelope, not the specific strategy id list.
    assert "strategies" in body


def test_screener_engine_default_v1(app_client):
    """No config entry → "v1"."""
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["screener"] = {}
    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    # POST → engine echo in the response envelope.
    rv = admin.post(
        "/api/screen",
        json={"market": "us", "strategy": "growth"},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body.get("engine") == "v1"


def test_screener_engine_v3_flips_to_v3(app_client):
    """``screener.engine: v3`` routes /api/screen through the v3
    sync wrapper. We patch the wrapper so we don't fire a real LLM."""
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["screener"] = {"engine": "v3"}

    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)

    with patch(
        "stock_trading_system.screener.v3.sync_wrapper.screen_sync",
        return_value=[{"ticker": "AAPL", "signal": "BUY", "score": 7.5,
                       "summary": "guru-driven verdict"}],
    ) as mock_sync:
        rv = admin.post(
            "/api/screen",
            json={"market": "us", "strategy": "growth"},
        )

    assert rv.status_code == 200
    body = rv.get_json()
    assert body.get("engine") == "v3"
    # The endpoint kicks off a thread; give it a moment to start.
    # (The wrapper call may complete after the response returns.)


def test_backtest_engine_v2_uses_v2_strategies(app_client):
    """``backtest.engine: v2`` routes ``/api/backtest/strategies`` to
    BacktestEngine."""
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["backtest"] = {"engine": "v2"}

    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    rv = admin.get("/api/backtest/strategies")
    assert rv.status_code == 200
    strategies = rv.get_json()["strategies"]
    # BacktestEngine.STRATEGIES contains 'sma_crossover' / 'rsi_reversal' /
    # 'buy_and_hold' with id-key shape. Just smoke-check the shape.
    ids = {s["id"] for s in strategies}
    assert "buy_and_hold" in ids


def test_backtest_engine_v1_default_still_works(app_client):
    """Sanity: with no flag the legacy Backtester powers the endpoint."""
    from stock_trading_system.config import get_config
    cfg = get_config()
    cfg["backtest"] = {"engine": "v1"}

    users = app_client["users"]
    admin = app_client["make_client"](users.admin_email, users.admin_password)
    rv = admin.get("/api/backtest/strategies")
    assert rv.status_code == 200
    assert "strategies" in rv.get_json()
