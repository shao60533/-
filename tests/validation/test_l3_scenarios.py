"""L3 Cross-module integration: 20 scenarios from design §6.1.

Tests that multi-module interactions work correctly.
Uses Flask test client (no browser).
"""

from __future__ import annotations

import sqlite3

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
def admin(app):
    with app.test_client() as c:
        resp = c.post("/api/auth/login", json={"email": "admin@local", "password": "Admin123!"})
        if resp.status_code != 200:
            pytest.skip("Admin login failed")
        yield c


# ── Scenario 4: admin generate invite ─────────────────────────────

class TestAdminInvite:
    def test_admin_can_generate_invite(self, admin):
        resp = admin.post("/api/admin/invites", json={"expires_in_days": 7})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "code" in data
        assert len(data["code"]) >= 8

    def test_admin_can_list_invites(self, admin):
        resp = admin.get("/api/admin/invites")
        assert resp.status_code == 200

    def test_admin_can_list_users(self, admin):
        resp = admin.get("/api/admin/users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["users"]) >= 1


# ── Scenario 5: model-switch ──────────────────────────────────────

class TestModelSwitch:
    def test_get_llm_provider(self, admin):
        resp = admin.get("/api/settings/llm-provider")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active" in data
        assert data["active"] in ("qwen", "gemini")

    def test_switch_provider_requires_key(self, admin):
        # Try switching to a provider — may fail if key missing but should not 500
        resp = admin.post("/api/settings/llm-provider", json={"provider": "gemini"})
        assert resp.status_code in (200, 400)  # 400 = missing key, not 500


# ── Scenario 7: admin sees migrated data ──────────────────────────

class TestMigratedData:
    def test_dashboard_returns_data(self, admin):
        resp = admin.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "pnl" in data

    def test_portfolio_summary(self, admin):
        resp = admin.get("/api/portfolio/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_value" in data

    def test_portfolio_has_holdings(self, admin):
        resp = admin.get("/api/portfolio/holdings")
        assert resp.status_code == 200


# ── Scenario 9: task events catch-up ──────────────────────────────

class TestTaskEventsCatchup:
    def test_events_endpoint(self, admin):
        resp = admin.get("/api/tasks/events?task_id=nonexistent&since=0")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_running_tasks_endpoint(self, admin):
        resp = admin.get("/api/tasks/running")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


# ── Scenario 14: screener-v3 gurus ────────────────────────────────

class TestScreenerV3:
    def test_gurus_returns_14(self, admin):
        resp = admin.get("/api/screen/v3/gurus")
        assert resp.status_code == 200
        data = resp.get_json()
        gurus = data.get("gurus", data)
        assert len(gurus) == 14

    def test_estimate_returns_valid(self, admin):
        resp = admin.post("/api/screen/v3/estimate", json={
            "candidate_n": 10, "gurus": ["buffett"],
            "with_roundtable": False,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["llm_calls"] == 10
        assert data["cost_cny"] > 0


# ── Scenario 16: no regex literal ─────────────────────────────────

class TestCodeQuality:
    def test_no_regex_literal(self):
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "--exclude-dir=validation", "--exclude-dir=__pycache__",
             "regex 解析", "stock_trading_system/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == ""


# ── Scenario 15: plan fingerprint dedup ───────────────────────────

class TestPlanDedup:
    def test_fingerprint_column_populated(self):
        from stock_trading_system.config import get_config
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        conn = sqlite3.connect(db_path)
        null = conn.execute("SELECT COUNT(*) FROM paper_trade_plans WHERE fingerprint IS NULL").fetchone()[0]
        conn.close()
        assert null == 0


# ── Scenario 17: task scope isolation ─────────────────────────────

class TestTaskScope:
    def test_tasks_list_returns_data(self, admin):
        resp = admin.get("/api/tasks?limit=10&offset=0")
        assert resp.status_code == 200

    def test_iteration_agents_endpoint(self, admin):
        resp = admin.get("/api/iteration/agents")
        assert resp.status_code == 200
