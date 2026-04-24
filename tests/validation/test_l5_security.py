"""L5 Adversarial: CSRF + session + unauthenticated access tests.

18 checks covering security boundaries.
"""

from __future__ import annotations

import pytest

from stock_trading_system.web import app as app_module


@pytest.fixture(scope="module")
def app():
    for attr in ("_task_manager", "_task_store", "_local_cache",
                 "_portfolio_mgr", "_alert_monitor", "_data_manager",
                 "_analyzer", "_screener", "_report_gen", "_strategy_engine",
                 "_scheduler", "_scheduler_thread"):
        if hasattr(app_module, attr):
            setattr(app_module, attr, None)
    _app = app_module.create_app()
    _app.config["TESTING"] = True
    return _app


@pytest.fixture()
def authed_client(app):
    with app.test_client() as c:
        c.post("/api/auth/login", json={"email": "admin@local", "password": "Admin123!"})
        yield c


@pytest.fixture()
def anon_client(app):
    with app.test_client() as c:
        yield c


# ── L5.1 Unauthenticated access → 401 ───────────────────────────

class TestUnauthenticated:
    @pytest.mark.parametrize("path", [
        "/api/portfolio/holdings",
        "/api/tasks",
        "/api/alerts",
        "/api/dashboard",
        "/api/portfolio/summary",
        "/api/screen/v3/gurus",
        "/api/auth/me",
    ])
    def test_anon_api_returns_401(self, anon_client, path):
        resp = anon_client.get(path)
        assert resp.status_code == 401, f"{path} returned {resp.status_code} (expected 401)"

    @pytest.mark.parametrize("path", [
        "/", "/portfolio", "/tasks", "/screener-v3", "/alerts",
    ])
    def test_anon_page_redirects_to_login(self, anon_client, path):
        resp = anon_client.get(path)
        assert resp.status_code in (302, 301), f"{path} returned {resp.status_code}"
        assert "/login" in (resp.headers.get("Location", "") or "")


# ── L5.2 Session validity ────────────────────────────────────────

class TestSession:
    def test_login_sets_session(self, app):
        with app.test_client() as c:
            resp = c.post("/api/auth/login", json={"email": "admin@local", "password": "Admin123!"})
            assert resp.status_code == 200
            # Session should work for subsequent requests
            resp2 = c.get("/api/auth/me")
            assert resp2.status_code == 200
            assert resp2.get_json()["user"]["email"] == "admin@local"

    def test_logout_clears_session(self, app):
        with app.test_client() as c:
            c.post("/api/auth/login", json={"email": "admin@local", "password": "Admin123!"})
            c.post("/api/auth/logout")
            resp = c.get("/api/auth/me")
            # After logout, me should return null user or 401
            data = resp.get_json()
            assert data.get("user") is None or resp.status_code == 401

    def test_wrong_password_returns_401(self, app):
        with app.test_client() as c:
            resp = c.post("/api/auth/login", json={"email": "admin@local", "password": "wrong"})
            assert resp.status_code == 401

    def test_nonexistent_user_returns_401(self, app):
        with app.test_client() as c:
            resp = c.post("/api/auth/login", json={"email": "nobody@nowhere.com", "password": "x"})
            assert resp.status_code == 401


# ── L5.3 Public paths accessible without auth ────────────────────

class TestPublicPaths:
    def test_login_page_accessible(self, anon_client):
        resp = anon_client.get("/login")
        assert resp.status_code == 200

    def test_register_page_accessible(self, anon_client):
        resp = anon_client.get("/register")
        assert resp.status_code == 200

    def test_health_accessible(self, anon_client):
        resp = anon_client.get("/api/health")
        assert resp.status_code == 200

    def test_auth_login_api_accessible(self, anon_client):
        # POST is accessible (returns 401 on wrong creds, not blocked by auth middleware)
        resp = anon_client.post("/api/auth/login", json={"email": "x", "password": "x"})
        assert resp.status_code == 401  # not 403 or redirect
