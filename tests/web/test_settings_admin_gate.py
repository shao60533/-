"""mobile-ui-v1.3.1 addendum #3 — admin gate on /settings + /api/settings*.

4 cases per the instruction §4 test plan:

  1. anon  GET  /settings        → 302 to /login (enforce_auth)
  2. user  GET  /settings        → 302 to /account
  3. admin GET  /settings        → 200, body references the settings island
  4. user  GET  /api/settings    → 403 (admin-only via @admin_required)

After rebasing onto hardening-iteration-v1 (P0.2), the API admin gate
is delivered by the shared `@admin_required` decorator (which returns
``{"error": "forbidden"}``) rather than the addendum's original inline
``_require_admin_json`` helper that emitted ``{"reason":"admin_only"}``.
The hardening shape is the new contract; assertions updated accordingly.
"""

from __future__ import annotations


def test_anon_get_settings_redirects_to_login(anon_client):
    rv = anon_client.get("/settings")
    assert rv.status_code in (302, 301)
    loc = rv.headers["Location"]
    assert "/login" in loc


def test_user_get_settings_redirects_to_account(alice_client):
    rv = alice_client.get("/settings", follow_redirects=False)
    assert rv.status_code in (302, 301)
    assert rv.headers["Location"].endswith("/account")


def test_admin_get_settings_returns_island(admin_client):
    rv = admin_client.get("/settings")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8")
    # vite_assets() rewrites the src entry into a hashed bundle name
    # (e.g. /static/dist/assets/settings-Cpwhmf-K.js) for prod builds;
    # we just assert the settings island chunk landed on the page.
    assert "/assets/settings-" in body
    assert 'name="user-role" content="admin"' in body


def test_user_api_settings_returns_403_admin_only(alice_client):
    rv = alice_client.get("/api/settings")
    assert rv.status_code == 403
    body = rv.get_json()
    assert body is not None
    # @admin_required (auth/decorators.py) emits {"error": "forbidden"};
    # the addendum's earlier reason="admin_only" shape was superseded
    # by the hardening rebase.
    assert body.get("error") == "forbidden"
