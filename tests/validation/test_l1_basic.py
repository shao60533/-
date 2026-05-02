"""L1 Basic: 33 checks — all pages load + basic CRUD via HTTP.

No browser needed — uses Flask test client.
"""

from __future__ import annotations

import pytest

from stock_trading_system.web import app as app_module


@pytest.fixture(scope="module")
def client():
    for attr in ("_task_manager", "_task_store", "_local_cache",
                 "_portfolio_mgr", "_alert_monitor", "_data_manager",
                 "_analyzer", "_screener", "_report_gen", "_strategy_engine",
                 "_scheduler", "_scheduler_thread"):
        if hasattr(app_module, attr):
            setattr(app_module, attr, None)

    app = app_module.create_app()
    app.config["TESTING"] = True

    from stock_trading_system.config import get_config
    cfg = get_config()

    with app.test_client() as c:
        # Login as admin
        resp = c.post("/api/auth/login", json={"email": "admin@local", "password": "Admin123!"})
        if resp.status_code != 200:
            pytest.skip("Admin login failed — DB not migrated?")
        yield c


# ── L1.1 Auth pages ──────────────────────────────────────────────

class TestAuthPages:
    def test_login_page_loads(self, client):
        # logout first to access login
        resp = client.get("/login")
        assert resp.status_code in (200, 302)

    def test_register_page_loads(self, client):
        resp = client.get("/register")
        assert resp.status_code in (200, 302)

    def test_auth_me_returns_user(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("user") is not None


# ── L1.2 React islands render ────────────────────────────────────

class TestReactIslands:
    @pytest.mark.parametrize("url", [
        "/", "/dashboard", "/screener-v3", "/tasks",
        "/portfolio", "/alerts",
        "/analysis", "/reports", "/settings",
    ])
    def test_react_island_loads(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "react-root" in html

    def test_history_redirects_to_analysis_inbox(self, client):
        """v1.22: ``/history`` was retired as a standalone island and
        now 301-redirects to the unified ``/analysis`` inbox."""
        resp = client.get("/history", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["Location"].endswith("/analysis")

    def test_legacy_spa_loads(self, client):
        resp = client.get("/app")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "page-dashboard" in html or "app.js" in html


# ── L1.3 API endpoints respond ───────────────────────────────────

class TestAPIEndpoints:
    @pytest.mark.parametrize("path", [
        "/api/dashboard",
        "/api/portfolio/holdings",
        "/api/portfolio/summary",
        "/api/portfolio/pnl",
        "/api/portfolio/history?days=30",
        "/api/alerts",
        "/api/history",
        "/api/tasks?limit=5",
        "/api/screen/v3/gurus",
        "/api/settings/llm-provider",
        "/api/auth/me",
        "/api/backtest/strategies",
    ])
    def test_api_responds_200(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"

    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200


# ── L1.4 CRUD operations ────────────────────────────────────────

class TestBasicCRUD:
    def test_portfolio_holdings_readable(self, client):
        """Verify holdings API returns valid list (read-only, no mutations)."""
        resp = client.get("/api/portfolio/holdings")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_alert_list_readable(self, client):
        """Verify alerts API returns valid data (read-only, no mutations)."""
        resp = client.get("/api/alerts")
        assert resp.status_code == 200

    def test_screener_v3_estimate(self, client):
        resp = client.post("/api/screen/v3/estimate", json={
            "candidate_n": 10, "gurus": ["buffett", "graham"],
            "with_roundtable": False,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "llm_calls" in data
        assert data["llm_calls"] == 20

    def test_task_list(self, client):
        resp = client.get("/api/tasks?limit=5&offset=0")
        assert resp.status_code == 200
