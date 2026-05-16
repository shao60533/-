"""Onboarding HTTP API (v1.0) tests.

10 cases per docs/design/onboarding.md §6.1:

  1.  GET  /api/onboarding/state          unauthenticated  → 401
  2.  GET  /api/onboarding/state          authenticated    → 200 + defaults
  3.  GET  /api/onboarding/state          cross-user isolated
  4.  POST /api/onboarding/mark-welcomed  tour_completed=false
  5.  POST /api/onboarding/mark-welcomed  tour_completed=true
  6.  POST /api/onboarding/dismiss-checklist
  7.  POST /api/onboarding/reset          clears + re-arms welcome_pending
  8.  there is NO  /api/onboarding/complete-step  public route (anti-spoof)
  9.  After init_for_new_user(alice) state.welcome_pending == True
 10.  init_for_new_user is idempotent + observable via API
"""

from __future__ import annotations


def _alice_id(app_client):
    return app_client["users"].alice.id


def _bob_id(app_client):
    return app_client["users"].bob.id


# ── 1 ─────────────────────────────────────────────────────────────────────
def test_state_requires_auth(anon_client):
    rv = anon_client.get("/api/onboarding/state")
    assert rv.status_code == 401


# ── 2 ─────────────────────────────────────────────────────────────────────
def test_state_returns_defaults_when_authed(alice_client):
    rv = alice_client.get("/api/onboarding/state")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body == {
        "welcome_pending": False,
        "welcomed": False,
        "tour_completed": False,
        "checklist_dismissed": False,
        "steps_completed": {},
    }


# ── 3 ─────────────────────────────────────────────────────────────────────
def test_state_isolated_across_users(app_client):
    from stock_trading_system.web import app as app_module
    app_module._onboarding_repo.init_for_new_user(_alice_id(app_client))
    app_module._onboarding_repo.mark_step(_alice_id(app_client), "add-holding")

    bob = app_client["make_client"](
        app_client["users"].bob_email, app_client["users"].bob_password,
    )
    rv = bob.get("/api/onboarding/state")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["welcome_pending"] is False
    assert body["steps_completed"] == {}

    alice = app_client["make_client"](
        app_client["users"].alice_email, app_client["users"].alice_password,
    )
    body = alice.get("/api/onboarding/state").get_json()
    assert body["welcome_pending"] is True
    assert body["steps_completed"] == {"add-holding": True}


# ── 4 ─────────────────────────────────────────────────────────────────────
def test_mark_welcomed_no_tour(alice_client):
    rv = alice_client.post(
        "/api/onboarding/mark-welcomed", json={"tour_completed": False},
    )
    assert rv.status_code == 200
    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["welcomed"] is True
    assert body["tour_completed"] is False
    assert body["welcome_pending"] is False


# ── 5 ─────────────────────────────────────────────────────────────────────
def test_mark_welcomed_with_tour(alice_client):
    rv = alice_client.post(
        "/api/onboarding/mark-welcomed", json={"tour_completed": True},
    )
    assert rv.status_code == 200
    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["welcomed"] is True
    assert body["tour_completed"] is True


# ── 6 ─────────────────────────────────────────────────────────────────────
def test_dismiss_checklist(alice_client):
    rv = alice_client.post("/api/onboarding/dismiss-checklist")
    assert rv.status_code == 200
    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["checklist_dismissed"] is True


# ── 7 ─────────────────────────────────────────────────────────────────────
def test_reset_clears_and_rearms(alice_client, app_client):
    from stock_trading_system.web import app as app_module
    app_module._onboarding_repo.mark_step(_alice_id(app_client), "add-holding")
    alice_client.post("/api/onboarding/mark-welcomed", json={"tour_completed": True})
    alice_client.post("/api/onboarding/dismiss-checklist")

    rv = alice_client.post("/api/onboarding/reset")
    assert rv.status_code == 200

    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["welcome_pending"] is True
    assert body["welcomed"] is False
    assert body["tour_completed"] is False
    assert body["checklist_dismissed"] is False
    assert body["steps_completed"] == {}


# ── 8 ─────────────────────────────────────────────────────────────────────
def test_no_public_complete_step_endpoint(alice_client):
    """Anti-spoof: front-end cannot self-mark steps. 404 must be returned."""
    rv = alice_client.post(
        "/api/onboarding/complete-step", json={"step_id": "add-holding"},
    )
    assert rv.status_code == 404


# ── 9 ─────────────────────────────────────────────────────────────────────
def test_init_for_new_user_sets_welcome_pending_observable(alice_client, app_client):
    from stock_trading_system.web import app as app_module
    app_module._onboarding_repo.init_for_new_user(_alice_id(app_client))
    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["welcome_pending"] is True


# ── 10 ────────────────────────────────────────────────────────────────────
def test_init_for_new_user_is_idempotent(alice_client, app_client):
    from stock_trading_system.web import app as app_module
    repo = app_module._onboarding_repo
    repo.init_for_new_user(_alice_id(app_client))
    # Simulate user dismissing then reset getting double-armed; init is idempotent
    repo.init_for_new_user(_alice_id(app_client))
    body = alice_client.get("/api/onboarding/state").get_json()
    assert body["welcome_pending"] is True
