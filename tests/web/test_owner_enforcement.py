"""P0.3 alerts / portfolio owner enforcement — closes C4 / C5 / C6.

Reference: docs/test-cases/hardening-iteration-v1.md §3.

Before this iteration:
    - C4 ``POST /api/alerts/remove`` did ``DELETE FROM alerts WHERE id = ?``
      with no user_id filter → any logged-in user could delete any
      other user's alert by guessing the id.
    - C5 ``GET /api/alerts/history`` returned every user's trigger
      rows; ``save_alert_trigger`` never populated ``alert_history.user_id``
      so the column existed but was always NULL.
    - C6 ``DELETE /api/portfolio/<ticker>``, ``POST /api/portfolio/update_cost``,
      ``POST /api/portfolio/snapshot`` had no explicit ``g.user`` check —
      they relied on ``enforce_auth`` and a silent ``_user_id() → None``
      fallback in PortfolioManager, which made the multi-tenant contract a
      convention rather than an enforced gate.
"""

from __future__ import annotations

import sqlite3

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _add_alert(db_path, user_id, ticker="AAPL", condition="price_above",
               threshold=200.0):
    """Insert an alert directly, return the new row id."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                condition   TEXT NOT NULL,
                threshold   REAL NOT NULL,
                triggered   INTEGER DEFAULT 0,
                created     TEXT NOT NULL,
                user_id     INTEGER
            )
        """)
        cur = conn.execute(
            "INSERT INTO alerts (ticker, condition, threshold, created, user_id) "
            "VALUES (?, ?, ?, datetime('now'), ?)",
            (ticker, condition, threshold, user_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_alert_history(db_path, alert_id, user_id, ticker="AAPL"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id        INTEGER NOT NULL,
                ticker          TEXT NOT NULL,
                condition       TEXT NOT NULL,
                threshold       REAL NOT NULL,
                current_price   REAL,
                triggered_at    TEXT NOT NULL,
                user_id         INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO alert_history "
            "(alert_id, ticker, condition, threshold, current_price, triggered_at, user_id) "
            "VALUES (?, ?, 'price_above', 200.0, 210.0, datetime('now'), ?)",
            (alert_id, ticker, user_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── TC-HD-C3-5: C4 — alerts.remove cross-tenant deletion blocked ─────────────


def test_alerts_remove_blocks_other_user(app_client, alice_client, bob_client):
    """Alice creates an alert; Bob tries to delete it via /api/alerts/remove.
    Must return 404 (not 403 — don't leak existence)."""
    alice_id = app_client["users"].alice.id
    alice_alert = _add_alert(app_client["db_path"], alice_id)

    rv = bob_client.post("/api/alerts/remove", json={"id": alice_alert})
    assert rv.status_code == 404, (
        f"Bob must not be able to delete Alice's alert; got {rv.status_code}. "
        f"Body: {rv.data!r}"
    )

    # Confirm the row is still there.
    conn = sqlite3.connect(app_client["db_path"])
    row = conn.execute("SELECT user_id FROM alerts WHERE id = ?",
                       (alice_alert,)).fetchone()
    conn.close()
    assert row is not None, "Alert was actually deleted!"
    assert row[0] == alice_id


def test_alerts_remove_works_for_owner(app_client, alice_client):
    """The owner can still delete their own alert."""
    alice_id = app_client["users"].alice.id
    alice_alert = _add_alert(app_client["db_path"], alice_id)

    rv = alice_client.post("/api/alerts/remove", json={"id": alice_alert})
    assert rv.status_code == 200


def test_alerts_remove_rejects_anon(anon_client):
    """Anonymous request — enforce_auth blocks before we even reach the route."""
    rv = anon_client.post("/api/alerts/remove", json={"id": 1})
    assert rv.status_code == 401


def test_alerts_remove_invalid_id(alice_client):
    """Missing or non-int id → 400, not 500."""
    rv = alice_client.post("/api/alerts/remove", json={})
    assert rv.status_code == 400


# ── TC-HD-C3-1 / C3-2: signature contracts ───────────────────────────────────


def test_monitor_remove_alert_requires_user_id():
    """AlertMonitor.remove_alert(alert_id) without user_id raises TypeError —
    the legacy signature is gone."""
    from stock_trading_system.alerts.monitor import AlertMonitor
    cfg = {"portfolio": {"db_path": ":memory:"}, "alerts": {}}
    monitor = AlertMonitor(cfg)
    with pytest.raises(TypeError):
        monitor.remove_alert(1)  # type: ignore[call-arg]


def test_db_remove_alert_does_not_delete_other_owner(app_client):
    """PortfolioDatabase.remove_alert(id, user_id) returns 0 when the alert
    exists but belongs to another user (no row deleted)."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id
    alert_id = _add_alert(app_client["db_path"], alice_id)

    deleted = db.remove_alert(alert_id, user_id=bob_id)
    assert deleted == 0, "remove_alert should return 0 for cross-owner delete"
    # And the row is intact:
    deleted_real = db.remove_alert(alert_id, user_id=alice_id)
    assert deleted_real == 1


# ── TC-HD-C3-6: C5 — alerts.history cross-tenant read blocked ────────────────


def test_alerts_history_only_returns_own_user(app_client, alice_client, bob_client):
    """alice has a trigger; bob asks /api/alerts/history → empty."""
    alice_id = app_client["users"].alice.id
    bob_id = app_client["users"].bob.id

    # Create one alert + history row for alice, one for bob.
    a_alert = _add_alert(app_client["db_path"], alice_id, ticker="AAPL")
    b_alert = _add_alert(app_client["db_path"], bob_id, ticker="AAPL")
    _insert_alert_history(app_client["db_path"], a_alert, alice_id)
    _insert_alert_history(app_client["db_path"], b_alert, bob_id)

    # Bob's view: only his own trigger.
    rv = bob_client.get("/api/alerts/history")
    assert rv.status_code == 200
    rows = rv.get_json()
    assert all(r["user_id"] == bob_id for r in rows), (
        f"Bob should not see other users' trigger rows. Got: {rows!r}"
    )

    # Alice's view: only hers.
    rv = alice_client.get("/api/alerts/history")
    rows = rv.get_json()
    assert all(r["user_id"] == alice_id for r in rows)


def test_alerts_history_anon_blocked(anon_client):
    rv = anon_client.get("/api/alerts/history")
    assert rv.status_code == 401


# ── TC-HD-C3-3: save_alert_trigger now persists user_id ──────────────────────


def test_save_alert_trigger_persists_user_id(app_client):
    """alert_history.user_id is no longer NULL after save_alert_trigger."""
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    alice_id = app_client["users"].alice.id
    alert_id = _add_alert(app_client["db_path"], alice_id)

    db.save_alert_trigger(
        alert_id, "AAPL", "price_above", 200.0, 210.0,
        user_id=alice_id,
    )

    conn = sqlite3.connect(app_client["db_path"])
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT user_id FROM alert_history WHERE alert_id = ?",
        (alert_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["user_id"] == alice_id, (
        f"alert_history.user_id should be {alice_id}, got {row['user_id']!r}"
    )


# ── TC-HD-C3-9..11: portfolio routes now have explicit g.user check ──────────


def test_portfolio_delete_anon_blocked(anon_client):
    rv = anon_client.delete("/api/portfolio/AAPL")
    assert rv.status_code == 401


def test_portfolio_update_cost_anon_blocked(anon_client):
    rv = anon_client.post("/api/portfolio/update_cost",
                          json={"ticker": "AAPL", "avg_cost": 150.0})
    assert rv.status_code == 401


def test_portfolio_snapshot_anon_blocked(anon_client):
    rv = anon_client.post("/api/portfolio/snapshot")
    assert rv.status_code == 401
