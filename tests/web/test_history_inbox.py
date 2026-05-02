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


def test_running_row_carries_all_required_fields(alice_client, app_client):
    """analysis-inbox v1.1: front-end ``RunningRow`` reads
    ``task_id / ticker / depth / status / submitted_at / progress_pct
    / progress_step / error / kind / created_by_name``. The response
    contract must keep every one of these fields populated for
    optimistic-row → live-row hand-off to work without a UI flicker."""
    alice_id = app_client["users"].alice.id
    tid = _submit_running_task(
        app_client, owner_id=alice_id, ticker="TSLA", status="running",
    )
    body = alice_client.get("/api/history?include_running=true").get_json()
    row = next(it for it in body["items"]
               if it["kind"] == "task" and it["task_id"] == tid)

    required_fields = {
        "kind", "task_id", "ticker", "depth", "status",
        "submitted_at", "progress_pct", "progress_step", "error",
        "created_by_name",
    }
    missing = required_fields - row.keys()
    assert not missing, f"missing required fields on inbox row: {missing}"

    # Concrete shape — guards against accidental dtype drift (e.g. a
    # future refactor returning ``progress_pct`` as a string would
    # break the front-end ``< 100`` comparison silently).
    assert row["kind"] == "task"
    assert row["task_id"] == tid
    assert row["ticker"] == "TSLA"
    assert row["depth"] == "standard"
    assert row["status"] == "running"
    assert isinstance(row["progress_pct"], int)
    assert row["progress_pct"] == 30  # value seeded by _submit_running_task
    # submitted_at is a wall-clock string (``YYYY-MM-DD HH:MM:SS``);
    # tolerate either format but require non-empty so the front-end
    # ``fmtRelative`` doesn't show "" instead of "刚刚".
    assert row["submitted_at"]


def test_submit_then_inbox_sees_running_row_immediately(alice_client, app_client):
    """End-to-end: submit through ``/api/tasks/submit`` and the very
    next ``/api/history?include_running=true`` MUST surface the new
    task row. This is the contract the front-end optimistic insert
    relies on (the optimistic row is replaced by the server-truth row
    on the first ``refreshInbox()`` after settle).

    We override the ``analysis`` worker with a blocking stub so the
    task stays in ``running`` long enough for the assert to fire — the
    real analyzer would race with the test."""
    import threading
    import time

    from stock_trading_system.web import app as app_module

    # Block the worker until the test releases the gate. This keeps
    # the task in ``running`` while we probe the inbox; it also lets
    # us verify the post-completion path before fixture teardown.
    gate = threading.Event()

    def blocking_worker(_params, progress_cb):
        progress_cb(15, "stub waiting")
        # 5s safety timeout so a botched test never deadlocks the suite.
        if not gate.wait(timeout=5.0):
            raise RuntimeError("test gate never released")
        progress_cb(100, "stub done")
        return {"signal": "HOLD", "ticker": _params.get("ticker", "AAPL")}

    # ``_task_manager`` is a lazy singleton — touching it via
    # ``_get_task_manager`` ensures the executor + worker registry
    # exist before we override the ``analysis`` slot.
    tm = app_module._get_task_manager()
    assert tm is not None, "task manager should be initialised by fixture"
    # Replace just for this test — TaskManager.register is a dict put
    # so we restore the real worker afterwards via teardown.
    original = tm._workers.get("analysis")
    tm.register("analysis", blocking_worker)
    try:
        rv = alice_client.post("/api/tasks/submit", json={
            "type": "analysis",
            "params": {"ticker": "AAPL", "date": "2026-05-02", "depth": "standard"},
        })
        assert rv.status_code == 200, rv.get_json()
        task_id = rv.get_json()["task_id"]

        # Give the executor a beat to pick up the task and flip status
        # to ``running`` (the gate.wait inside the worker means it'll
        # stay there). 50ms is plenty even on a loaded CI box.
        time.sleep(0.1)

        body = alice_client.get(
            "/api/history?include_running=true",
        ).get_json()
        running = [it for it in body["items"]
                   if it["kind"] == "task" and it["task_id"] == task_id]
        assert len(running) == 1, (
            f"submit→inbox: task {task_id} not found, "
            f"got {[(it['kind'], it.get('task_id')) for it in body['items']]}"
        )
        assert running[0]["ticker"] == "AAPL"
        assert running[0]["depth"] == "standard"
        assert running[0]["status"] in ("pending", "running")

        # Release the worker and wait for completion so fixture
        # teardown's ``shutdown(wait=True)`` doesn't hit a hung task.
        gate.set()
        for _ in range(50):  # up to 5s
            poll = alice_client.get(f"/api/tasks/{task_id}").get_json()
            if poll.get("status") in ("success", "failed", "cancelled"):
                break
            time.sleep(0.1)
    finally:
        gate.set()
        if original is not None:
            tm.register("analysis", original)


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
