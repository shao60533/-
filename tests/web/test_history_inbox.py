"""v1.22 unified analysis inbox: ``/api/history?include_running=true``
returns active analysis tasks merged with completed analysis_history
rows, deduped by ``task_id``. Without the flag the legacy v1.18
contract holds (completed-only, no auth gate)."""

from __future__ import annotations

import sqlite3


def _submit_running_task(app_client, *, owner_id: int, ticker: str = "AAPL",
                          status: str = "running") -> str:
    """Insert a row directly into the ``tasks`` table so we don't have
    to spin up a real worker. Mirrors the columns ``TaskManager.submit``
    writes. Forces the table to exist via TaskStore init first."""
    import json as _json
    import uuid

    from stock_trading_system.tasks.task_store import TaskStore

    db_path = app_client["db_path"]
    # Ensure the schema is up — ``tasks`` is created lazily by TaskStore
    # init, which the bare seeding below otherwise wouldn't trigger.
    TaskStore(db_path)
    tid = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO tasks
               (id, type, title, params_json, status, progress,
                created_at, created_by)
               VALUES (?, 'analysis', 'AI 分析', ?, ?, ?,
                       datetime('now'), ?)""",
            (
                tid,
                _json.dumps({"ticker": ticker, "depth": "standard"}),
                status, 30, str(owner_id),
            ),
        )
    return tid


def _seed_analysis(app_client, *, owner_id: int, ticker: str = "MSFT",
                    signal: str = "BUY", task_id: str | None = None) -> int:
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-05-01", "signal": signal,
        "created_by": owner_id,
        "task_id": task_id,
    })


# ── Inbox shape ─────────────────────────────────────────────────────────


def test_inbox_returns_active_tasks_alongside_completed(alice_client, app_client):
    alice_id = app_client["users"].alice.id
    tid = _submit_running_task(app_client, owner_id=alice_id, ticker="AAPL")
    _seed_analysis(app_client, owner_id=alice_id, ticker="MSFT", signal="BUY")
    _seed_analysis(app_client, owner_id=alice_id, ticker="NVDA", signal="HOLD")

    body = alice_client.get(
        "/api/history?include_running=true",
    ).get_json()

    kinds = [it["kind"] for it in body["items"]]
    assert kinds.count("task") == 1
    assert kinds.count("analysis") == 2
    assert body["running_total"] == 1
    assert body["completed_total"] == 2
    # Running task carries discriminator + task metadata.
    task_row = next(it for it in body["items"] if it["kind"] == "task")
    assert task_row["task_id"] == tid
    assert task_row["ticker"] == "AAPL"
    assert task_row["depth"] == "standard"


def test_inbox_running_only_self(alice_client, bob_client, app_client):
    """Running tasks are user-scoped — Alice's task never appears in
    Bob's inbox even though analysis_history rows are shared research."""
    alice_id = app_client["users"].alice.id
    _submit_running_task(app_client, owner_id=alice_id, ticker="AAPL")
    body = bob_client.get("/api/history?include_running=true").get_json()
    assert all(it["kind"] != "task" for it in body["items"])
    assert body["running_total"] == 0


def test_inbox_dedupes_completed_when_task_still_active(alice_client, app_client):
    """Same logical analysis appears as both a row in analysis_history
    (worker landed it early) AND an active task — surface only the task
    row until the task settles."""
    alice_id = app_client["users"].alice.id
    tid = _submit_running_task(app_client, owner_id=alice_id, ticker="AAPL")
    _seed_analysis(
        app_client, owner_id=alice_id, ticker="AAPL", signal="BUY",
        task_id=tid,
    )
    body = alice_client.get("/api/history?include_running=true").get_json()
    aapl = [it for it in body["items"] if it["ticker"] == "AAPL"]
    assert len(aapl) == 1
    assert aapl[0]["kind"] == "task"


def test_inbox_keeps_completed_when_task_settled(alice_client, app_client):
    """If the task has progressed to a terminal status that the inbox
    doesn't surface (e.g. ``success``), the completed row carries on."""
    alice_id = app_client["users"].alice.id
    tid = _submit_running_task(
        app_client, owner_id=alice_id, ticker="AAPL", status="success",
    )
    _seed_analysis(
        app_client, owner_id=alice_id, ticker="AAPL", signal="BUY",
        task_id=tid,
    )
    body = alice_client.get("/api/history?include_running=true").get_json()
    aapl = [it for it in body["items"] if it["ticker"] == "AAPL"]
    # 1 row, completed (success isn't in the inbox's active filter).
    assert len(aapl) == 1
    assert aapl[0]["kind"] == "analysis"


def test_inbox_failed_task_surfaces_in_running_list(alice_client, app_client):
    """Failed tasks carry actionable retry context — keep them visible
    in the inbox under ``kind: 'task'`` until the user dismisses /
    retries them."""
    alice_id = app_client["users"].alice.id
    _submit_running_task(
        app_client, owner_id=alice_id, ticker="AAPL", status="failed",
    )
    body = alice_client.get("/api/history?include_running=true").get_json()
    failed = [it for it in body["items"]
              if it["kind"] == "task" and it["status"] == "failed"]
    assert len(failed) == 1


def test_inbox_requires_login(anon_client):
    rv = anon_client.get("/api/history?include_running=true")
    assert rv.status_code == 401


def test_inbox_orders_newest_first(alice_client, app_client):
    """Mixed task + analysis items sort by ``submitted_at``/``created_at``
    descending so the freshest activity is on top. Use explicit
    far-future + far-past timestamps so the assertion isn't sensitive
    to test machine local-time vs sqlite UTC drift."""
    import json as _json
    import sqlite3 as _sqlite3
    import uuid as _uuid

    from stock_trading_system.portfolio.database import PortfolioDatabase
    from stock_trading_system.tasks.task_store import TaskStore

    alice_id = app_client["users"].alice.id
    db_path = app_client["db_path"]
    TaskStore(db_path)
    PortfolioDatabase(db_path).save_analysis({
        "ticker": "MSFT", "date": "2026-04-30", "signal": "BUY",
        "created_by": alice_id,
        "created_at": "2026-04-30 10:00:00",
    })
    tid = str(_uuid.uuid4())
    with _sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO tasks
               (id, type, title, params_json, status, progress,
                created_at, created_by)
               VALUES (?, 'analysis', 'AI 分析', ?, 'running', 30,
                       '2099-01-01 00:00:00', ?)""",
            (tid, _json.dumps({"ticker": "AAPL"}), str(alice_id)),
        )
    body = alice_client.get("/api/history?include_running=true").get_json()
    assert body["items"][0]["ticker"] == "AAPL"
    assert body["items"][0]["kind"] == "task"


# ── Legacy contract (no include_running) ────────────────────────────────


def test_legacy_contract_unchanged_without_include_running(
    alice_client, app_client,
):
    alice_id = app_client["users"].alice.id
    _submit_running_task(app_client, owner_id=alice_id)
    _seed_analysis(app_client, owner_id=alice_id, ticker="MSFT")
    body = alice_client.get("/api/history").get_json()
    # Legacy shape: items + records + count, no kind discriminator,
    # no running_total / completed_total.
    assert "running_total" not in body
    assert "completed_total" not in body
    assert "count" in body
    assert "records" in body
    assert all("kind" not in it for it in body["items"])


def test_legacy_logged_in_call_unchanged(alice_client, app_client):
    """Authenticated callers without ``include_running`` see the v1.18
    shape exactly — proves we didn't accidentally break dashboards that
    still call /api/history with the old contract. (The global auth
    middleware blocks anon ``/api/*`` regardless of endpoint, so the
    older anon-tolerant test was misconceived.)"""
    alice_id = app_client["users"].alice.id
    _seed_analysis(app_client, owner_id=alice_id, ticker="MSFT")
    body = alice_client.get("/api/history").get_json()
    assert isinstance(body.get("items"), list)
    assert isinstance(body.get("records"), list)
    assert isinstance(body.get("count"), int)
