"""Async task dispatcher — thread pool + worker registry + WebSocket events.

Responsibilities:
- Register worker functions keyed by task_type.
- Submit tasks (idempotent within a time window).
- Execute in a ThreadPoolExecutor, relaying progress via callback → WS.
- Persist full lifecycle to TaskStore.
- Support retry, cancel, list, get.

WebSocket events emitted (ARCHITECTURE_UPGRADE_PROPOSAL §4.2.6):
    task_created    — {id, type, title, params_json, ...}
    task_started    — {id}
    task_progress   — {id, progress, step, partial?}
    task_completed  — {id, result_ref}
    task_failed     — {id, error_message}
    task_cancelled  — {id}
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Iterable

from stock_trading_system.tasks.task_store import (
    TaskStore, hash_params, now_iso,
)
from stock_trading_system.utils import get_logger

logger = get_logger("tasks.manager")


# A worker callable takes (params_dict, progress_cb) and returns result dict.
# progress_cb(percent, step_desc=None, partial=None) is safe to call at will.
WorkerFn = Callable[[dict, Callable[..., None]], dict]


def _gen_title(task_type: str, params: dict) -> str:
    """Human-readable auto title for tasks."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ticker = params.get("ticker")
    if task_type == "analysis":
        return f"{ticker or '未指定'} 分析 · {ts}"
    if task_type == "screen":
        market = (params.get("market") or "").upper()
        strategy = params.get("strategy") or ""
        return f"{market}{strategy} 选股 · {ts}"
    if task_type == "backtest":
        strat = params.get("strategy_id") or ""
        return f"{strat} 回测 {ticker or ''} · {ts}".strip()
    if task_type == "report":
        rtype = params.get("type") or ""
        return f"{rtype} 报告 · {ts}"
    if task_type.startswith("qwen_"):
        return f"{task_type} · {ticker or ''} · {ts}"
    return f"{task_type} · {ts}"


class _NoopSocketIO:
    """Fallback when no socketio instance is provided (tests)."""

    def emit(self, *args, **kwargs):  # pragma: no cover — trivial
        pass


class TaskManager:
    """Submit/execute tasks with persistence and live progress."""

    def __init__(
        self,
        store: TaskStore,
        socketio: Any | None = None,
        max_workers: int = 3,
        default_idempotency_window: int = 60,
    ):
        self._store = store
        self._socketio = socketio or _NoopSocketIO()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="task-worker",
        )
        self._default_window = int(default_idempotency_window)
        self._workers: dict[str, WorkerFn] = {}
        # task_id -> (Future, cancel_event)
        self._running: dict[str, tuple[Future, threading.Event]] = {}
        self._lock = threading.Lock()
        # Recover from prior crash: mark any orphaned running tasks as failed.
        try:
            n = self._store.mark_orphaned_running_as_failed(reason="服务中断")
            if n:
                logger.info("Marked %d orphaned running tasks as failed", n)
        except Exception as e:  # noqa: BLE001
            logger.warning("Orphan recovery failed: %s", e)

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, task_type: str, worker_fn: WorkerFn) -> None:
        self._workers[task_type] = worker_fn
        logger.info("Registered worker: %s", task_type)

    def registered_types(self) -> list[str]:
        return sorted(self._workers.keys())

    # ── Submission ───────────────────────────────────────────────────────

    def submit(
        self,
        task_type: str,
        params: dict,
        title: str | None = None,
        idempotency_window: int | None = None,
        created_by: int | str | None = None,
    ) -> dict:
        """Submit a task. Returns the persisted task dict.

        If an identical task (same type + params) exists within
        *idempotency_window* seconds in status (pending/running/success),
        that task is returned instead and no new worker runs.

        Pass idempotency_window=0 to force a brand-new task.

        Multi-tenant: if caller didn't pass created_by, infer from Flask g.user
        so per-user task lists work without every route remembering to pass it.
        Falls back to legacy "user" string in non-request contexts (cron, CLI).
        """
        if created_by is None:
            try:
                from flask import g, has_request_context
                if has_request_context() and getattr(g, "user", None):
                    created_by = g.user.id
            except Exception:
                pass
            if created_by is None:
                created_by = "user"
        window = (
            self._default_window
            if idempotency_window is None
            else int(idempotency_window)
        )
        params = params or {}
        phash = hash_params(task_type, params)

        # Idempotency check
        if window > 0:
            existing = self._store.find_recent_by_hash(
                phash, window_seconds=window,
                statuses=("pending", "running", "success"),
            )
            if existing:
                logger.info(
                    "Idempotent hit for %s: reusing task %s", task_type, existing["id"]
                )
                return existing

        task_id = str(uuid.uuid4())
        task_row = {
            "id": task_id,
            "type": task_type,
            "title": title or _gen_title(task_type, params),
            "params_json": json.dumps(params, ensure_ascii=False),
            "status": "pending",
            "params_hash": phash,
            "created_by": created_by,
        }
        inserted = self._store.insert(task_row)

        self._emit("task_created", inserted)

        # Unknown worker — fail fast so the task row shows a clear reason.
        if task_type not in self._workers:
            self._fail(
                task_id, f"Unknown task type: {task_type}",
                "TaskManager has no worker registered for this type.",
            )
            return self._store.get(task_id)

        cancel_event = threading.Event()
        future = self._executor.submit(self._run, task_id, task_type, params, cancel_event)
        with self._lock:
            self._running[task_id] = (future, cancel_event)
        future.add_done_callback(lambda _f, tid=task_id: self._cleanup_running(tid))
        return inserted

    # ── Execution ────────────────────────────────────────────────────────

    def _run(
        self, task_id: str, task_type: str, params: dict, cancel_event: threading.Event
    ) -> None:
        if cancel_event.is_set():
            # Task cancelled before worker even started
            self._store.update(task_id, status="cancelled", completed_at=now_iso())
            self._emit("task_cancelled", {"id": task_id})
            return

        worker = self._workers.get(task_type)
        started = time.perf_counter()
        self._store.update(task_id, status="running", started_at=now_iso(), progress=0)
        self._emit("task_started", {"id": task_id})

        def progress_cb(
            percent: float | int,
            step_desc: str | None = None,
            partial: Any = None,
        ) -> None:
            try:
                pct = max(0, min(99, int(percent)))  # reserve 100 for completion
            except (TypeError, ValueError):
                pct = 0
            self._store.update(task_id, progress=pct, progress_step=step_desc)
            self._emit("task_progress", {
                "id": task_id, "progress": pct,
                "step": step_desc, "partial": partial,
            })

        try:
            if cancel_event.is_set():
                raise _CancelledError("Cancelled before execution")
            # Inject task_id so workers can persist it in result tables (read-only key)
            # Inject cancel_event so workers can implement cooperative cancellation
            params_with_id = dict(params)
            params_with_id["__task_id__"] = task_id
            params_with_id["__cancel_event__"] = cancel_event
            result = worker(params_with_id, progress_cb) or {}
            # Persist the result to its business table.
            # Workers may pre-persist and return a result_ref of the form
            # "<table>:<id>" — in that case we honor it instead of saving again.
            ref_from_worker = result.get("result_ref") if isinstance(result, dict) else None
            if isinstance(ref_from_worker, str) and ":" in ref_from_worker:
                result_ref = ref_from_worker
            else:
                result_ref = self._store.save_result(task_type, task_id, result)
            # ── Post-save hooks ─────────────────────────────────────────
            # Workers (currently only `analysis`) can attach side-effects
            # to the canonical analysis_id without doubling up writes. The
            # hook returns silently on failure so the task itself still
            # marks success — these side-effects are auditing, not core.
            if task_type == "analysis" and isinstance(result, dict) \
                    and isinstance(result_ref, str) \
                    and result_ref.startswith("analysis_history:"):
                self._post_analysis_save(result_ref, result)
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._store.update(
                task_id,
                status="success",
                progress=100,
                progress_step=None,
                result_ref=result_ref,
                completed_at=now_iso(),
                duration_ms=duration_ms,
            )
            self._emit("task_completed", {"id": task_id, "result_ref": result_ref})
        except _CancelledError as e:
            self._store.update(
                task_id, status="cancelled",
                completed_at=now_iso(),
                error_message=str(e),
            )
            self._emit("task_cancelled", {"id": task_id})
        except Exception as e:  # noqa: BLE001 — capture all worker failures
            self._fail(task_id, str(e), traceback.format_exc())

    def _fail(self, task_id: str, error_message: str, error_trace: str) -> None:
        self._store.update(
            task_id,
            status="failed",
            error_message=error_message,
            error_trace=error_trace,
            completed_at=now_iso(),
        )
        self._emit("task_failed", {
            "id": task_id, "error_message": error_message,
        })

    def _cleanup_running(self, task_id: str) -> None:
        with self._lock:
            self._running.pop(task_id, None)

    # ── Control ──────────────────────────────────────────────────────────

    def retry(self, original_task_id: str) -> dict:
        """Clone a task and re-submit with retry_of pointing to original."""
        orig = self._store.get(original_task_id)
        if not orig:
            raise ValueError(f"Task not found: {original_task_id}")
        params = json.loads(orig["params_json"]) if orig["params_json"] else {}
        new_task = self.submit(
            orig["type"], params,
            title=f"{orig['title']} (重试)",
            idempotency_window=0,  # force new
            created_by=orig.get("created_by", "user"),
        )
        # Record the retry lineage
        self._store.update(new_task["id"], retry_of=original_task_id)
        return self._store.get(new_task["id"])

    def cancel(self, task_id: str) -> bool:
        """Attempt to cancel a pending or running task.

        Returns True if the task moved to cancelled state.
        """
        task = self._store.get(task_id)
        if not task:
            return False
        if task["status"] not in ("pending", "running"):
            return False
        with self._lock:
            entry = self._running.get(task_id)
        if entry is None:
            # Was pending in DB but not in pool (shouldn't happen) — mark directly
            self._store.update(task_id, status="cancelled", completed_at=now_iso())
            self._emit("task_cancelled", {"id": task_id})
            return True
        future, cancel_event = entry
        cancel_event.set()
        cancelled = future.cancel()  # only works if not yet running
        if cancelled:
            self._store.update(task_id, status="cancelled", completed_at=now_iso())
            self._emit("task_cancelled", {"id": task_id})
            return True
        # Running worker must check cancel_event to honor cancellation.
        # Current built-in workers treat it as cooperative; status flip
        # happens when _run() observes the event and raises _CancelledError.
        # For the API contract we still say "yes, we requested it".
        return True

    # ── Queries ──────────────────────────────────────────────────────────

    def get(self, task_id: str) -> dict | None:
        return self._store.get(task_id)

    def list(
        self,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        created_by: int | None = None,
        scope: str | None = None,
    ) -> list[dict]:
        return self._store.list(task_type, status, limit, offset,
                                created_by=created_by, scope=scope)

    def count(
        self,
        task_type: str | None = None,
        status: str | None = None,
        created_by: int | None = None,
        scope: str | None = None,
    ) -> int:
        return self._store.count(task_type=task_type, status=status,
                                 created_by=created_by, scope=scope)

    def get_result(self, task_id: str) -> dict | None:
        task = self._store.get(task_id)
        if not task or not task.get("result_ref"):
            return None
        return self._store.load_result(task["result_ref"])

    def delete(self, task_id: str) -> bool:
        return self._store.delete(task_id)

    # ── Plumbing ─────────────────────────────────────────────────────────

    def _emit(self, event: str, payload: dict) -> None:
        """Emit a lifecycle event.

        Three concerns the implementation honors:
            1. Persist to task_events so reconnecting clients can catch up.
            2. Broadcast on the *injected* socketio so tests and per-app
               instances both see every event — never reach for the module-
               level global, which would skip the test recorder.
            3. Scope the broadcast to ``user:{created_by}`` when we know the
               owner, so users only see their own task lifecycle events.
        """
        task_id = payload.get("task_id") or payload.get("id", "")

        # Persist (best effort; no-op when task_events table is absent).
        user_id: int | str | None = None
        if task_id:
            try:
                from stock_trading_system.tasks.event_emitter import (
                    persist_event, _resolve_db_path, _resolve_user_id,
                )
                db_path = _resolve_db_path(getattr(self._store, "_db_path", None))
                user_id = _resolve_user_id(db_path, task_id)
                persist_event(
                    task_id, event, payload,
                    db_path=db_path, user_id=user_id,
                )
            except Exception as e:  # pragma: no cover
                logger.debug("persist_event failed for %s: %s", event, e)

        # Broadcast on the injected socketio. Use a per-user room when we know
        # the owner so cross-user leakage doesn't happen in production; tests
        # using RecordingSocketIO ignore the `to=` kwarg.
        try:
            if user_id is not None:
                self._socketio.emit(event, payload, to=f"user:{user_id}")
            else:
                self._socketio.emit(event, payload)
        except Exception as e:  # pragma: no cover
            logger.warning("WS emit failed for %s: %s", event, e)

    def _post_analysis_save(self, result_ref: str, result: dict) -> None:
        """Side-effect hook fired after _save_analysis_result wrote a row.

        Two consumers today:
          1. ``user_analysis_advice`` — per-user, holdings-aware position
             sizing + reasoning. Stripped from the shared row so cross-user
             reads don't leak portfolio context.
          2. ``record_analysis`` (per-agent scorecards) — only fires when
             iteration is enabled and the worker captured a final_state.

        Both of these used to live inside the worker, where the scorecard
        path called ``db.save_analysis(...)`` just to mint an id and
        thereby double-recorded every iterated analysis. Doing them here
        with the canonical id keeps the analysis_history table single-row.
        """
        try:
            analysis_id = int(result_ref.split(":", 1)[1])
        except (ValueError, IndexError) as e:
            logger.warning("post-analysis hook: bad result_ref %s: %s", result_ref, e)
            return

        # 1) Per-user advice
        advice_payload = result.get("_advice_payload")
        created_by = result.get("created_by")
        if advice_payload and created_by is not None:
            try:
                from stock_trading_system.config import get_config
                from stock_trading_system.portfolio.database import PortfolioDatabase
                cfg = get_config()
                db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
                pdb = PortfolioDatabase(db_path)
                pdb.save_user_advice(
                    user_id=int(created_by),
                    analysis_id=analysis_id,
                    advice=advice_payload.get("advice") or {},
                    holdings_snapshot=advice_payload.get("holdings_snapshot") or "",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("save_user_advice failed for analysis %s: %s",
                               analysis_id, e)

        # 2) Agent scorecards (iteration-only)
        final_state_blob = result.get("_final_state_json")
        if final_state_blob:
            try:
                from stock_trading_system.config import get_config
                from stock_trading_system.tasks.workers import (
                    record_agent_scores_for_analysis, deserialize_final_state,
                )
                cfg = get_config()
                db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
                final_state = deserialize_final_state(final_state_blob)
                if final_state is not None:
                    # Resolve a router lazily — avoid importing web.app here.
                    def _get_router_lazy():
                        try:
                            from stock_trading_system.web.app import _get_data_router
                            return _get_data_router()
                        except Exception:  # noqa: BLE001
                            return None
                    record_agent_scores_for_analysis(
                        analysis_id=analysis_id,
                        final_state=final_state,
                        ticker=result.get("ticker", ""),
                        date=result.get("date", ""),
                        get_router=_get_router_lazy,
                        db_path=db_path,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("agent score record failed for analysis %s: %s",
                               analysis_id, e)

        # 3) Auto-drive paper trade for the requesting user (best-effort).
        # Failures are logged but never block the analysis task — paper
        # trade is a side-effect, not the primary outcome of /api/analyze.
        if advice_payload and created_by is not None:
            try:
                from stock_trading_system.config import get_config
                from stock_trading_system.strategy.paper_trader import (
                    PaperTradeStore, process_analysis,
                )
                cfg = get_config()
                db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
                store = PaperTradeStore(db_path)
                current_price: float | None = None
                try:
                    from stock_trading_system.web.app import _get_data_router
                    router = _get_data_router()
                    if router:
                        pd = router.get_price(result.get("ticker", ""))
                        if pd:
                            current_price = pd.get("last") or pd.get("close")
                except Exception as e:  # noqa: BLE001
                    logger.debug("price lookup for auto paper-trade failed: %s", e)
                process_analysis(
                    store,
                    analysis_id=analysis_id,
                    ticker=result.get("ticker", ""),
                    analysis_date=result.get("date") or "",
                    signal=result.get("signal", ""),
                    advice=advice_payload.get("advice") or {},
                    current_price=current_price,
                    user_id=int(created_by),
                    analysis_blob={
                        "trade_decision":   result.get("trade_decision", ""),
                        "risk_assessment":  result.get("risk_assessment", ""),
                        "investment_debate": result.get("investment_debate", ""),
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "auto paper-trade for analysis %s failed (non-fatal): %s",
                    analysis_id, e,
                )

    def wait_for(self, task_id: str, timeout: float | None = None) -> dict | None:
        """Block until a task reaches a terminal state. Test convenience."""
        with self._lock:
            entry = self._running.get(task_id)
        if entry is None:
            return self._store.get(task_id)
        future, _ = entry
        try:
            future.result(timeout=timeout)
        except Exception:  # noqa: BLE001 — we don't care, just return row
            pass
        return self._store.get(task_id)

    def cancel_all(self) -> int:
        """Signal every currently-tracked running task to stop.

        Returns the count of tasks that received the signal. Cooperative —
        a worker that ignores its ``__cancel_event__`` will keep running
        until it returns naturally.
        """
        with self._lock:
            ids = list(self._running.keys())
        signaled = 0
        for tid in ids:
            try:
                if self.cancel(tid):
                    signaled += 1
            except Exception:  # pragma: no cover
                pass
        return signaled

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Stop the executor.

        ``cancel_futures=True`` (Python 3.9+) cancels queued-but-not-yet-running
        futures so test teardown doesn't have to wait for the whole backlog.
        Already-running workers still run to completion when ``wait=True``.
        """
        try:
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        except TypeError:
            # Older Python — fall back to the original signature.
            self._executor.shutdown(wait=wait)


class _CancelledError(Exception):
    """Internal marker for cooperative cancellation."""
