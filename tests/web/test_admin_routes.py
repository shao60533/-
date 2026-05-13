"""P0.2 Missing @admin_required — gates that were declared in
docs/design/multi-tenant.md §5.5 but never wired in web/app.py:
  - /api/settings (GET + POST) — fixed C3
  - /api/scheduler/start|stop — fixed H1 (partial fix; /run-now already had gate)

Reference: docs/test-cases/hardening-iteration-v1.md §2 (TC-HD-C2-1 .. C2-6).

For each protected route we assert two scenarios:
    1. role=user gets 403 (the gate works for non-admin)
    2. role=admin sees the route execute (200 or other business code)
"""

from __future__ import annotations


def _assert_403(rv, route_name):
    assert rv.status_code == 403, (
        f"{route_name} must return 403 for role=user; got {rv.status_code}. "
        f"Body: {rv.data!r}"
    )


def _assert_not_403(rv, route_name):
    assert rv.status_code != 403, (
        f"{route_name} must execute for admin (not 403). "
        f"Got {rv.status_code}. Body: {rv.data!r}"
    )


# ── TC-HD-C2-1: GET /api/settings ─────────────────────────────────────────


def test_settings_get_blocks_user(alice_client):
    rv = alice_client.get("/api/settings")
    _assert_403(rv, "GET /api/settings")


def test_settings_get_allows_admin(admin_client):
    rv = admin_client.get("/api/settings")
    _assert_not_403(rv, "GET /api/settings (admin)")


# ── TC-HD-C2-2: POST /api/settings (the C3 fix) ────────────────────────────


def test_settings_post_blocks_user(alice_client):
    rv = alice_client.post("/api/settings", json={"gemini.api_key": "stolen"})
    _assert_403(rv, "POST /api/settings")


def test_settings_post_allows_admin(admin_client):
    rv = admin_client.post("/api/settings", json={"gemini.api_key": "AIzaTest"})
    _assert_not_403(rv, "POST /api/settings (admin)")


# ── TC-HD-C2-3 / C2-4: POST /api/scheduler/start|stop ──────────────────────


def test_scheduler_start_blocks_user(alice_client):
    rv = alice_client.post("/api/scheduler/start", json={})
    _assert_403(rv, "POST /api/scheduler/start")


def test_scheduler_stop_blocks_user(alice_client):
    rv = alice_client.post("/api/scheduler/stop", json={})
    _assert_403(rv, "POST /api/scheduler/stop")


# ── TC-HD-C2-5: POST /api/scheduler/run-now (already had gate, regression) ─


def test_scheduler_run_now_blocks_user(alice_client):
    rv = alice_client.post("/api/scheduler/run-now", json={})
    _assert_403(rv, "POST /api/scheduler/run-now")


# ── TC-HD-C2-6: POST /api/admin/invites (already had gate, regression) ─────


def test_admin_invites_blocks_user(alice_client):
    rv = alice_client.post("/api/admin/invites", json={})
    _assert_403(rv, "POST /api/admin/invites")
