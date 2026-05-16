"""APScheduler-backed daily-snapshot job.

Runs once at 16:30 America/New_York (post-close), iterates every active
user, and asks the per-user :class:`PortfolioManager` to take a snapshot.
Replaces the half-wired ``schedule``-library job that the dev's box has
been quietly skipping for two weeks.

Boot wiring:
    DailySnapshotScheduler.start_if_primary() — only starts inside a
    process that holds the "primary" role (gunicorn worker 0, or the
    single-process dev runner). Multi-worker deployments otherwise emit
    duplicate snapshots once a day; we use a small filesystem lock under
    ``~/.stock_trading/scheduler.lock`` to nominate one worker.

Operator surfaces:
    .status()      — what /api/scheduler/status renders.
    .run_now()     — what /api/scheduler/run-now triggers.
    .next_run()    — convenience for the dashboard / UI.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_trading_system.utils import get_logger

logger = get_logger("scheduler.daily_snapshot")


_DEFAULT_CRON = {"hour": 16, "minute": 30, "timezone": "America/New_York"}
_JOB_ID = "daily_snapshot"


class DailySnapshotScheduler:
    """Wraps a single APScheduler ``BackgroundScheduler`` instance."""

    _instance: Optional["DailySnapshotScheduler"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        snapshot_fn: Callable[[], Any],
        *,
        cron_kwargs: dict | None = None,
    ):
        self._snapshot_fn = snapshot_fn
        self._cron_kwargs = cron_kwargs or _DEFAULT_CRON
        self._scheduler = BackgroundScheduler(daemon=True)
        self._lock_file: Path | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    @classmethod
    def get(
        cls,
        snapshot_fn: Callable[[], Any] | None = None,
        *,
        cron_kwargs: dict | None = None,
    ) -> "DailySnapshotScheduler":
        """Module-level singleton accessor.

        ``snapshot_fn`` is required on first call. On subsequent calls we
        ignore it — the job has already been wired.
        """
        with cls._lock:
            if cls._instance is None:
                if snapshot_fn is None:
                    raise RuntimeError(
                        "DailySnapshotScheduler not initialized; "
                        "first call must pass snapshot_fn."
                    )
                cls._instance = cls(snapshot_fn, cron_kwargs=cron_kwargs)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test-only: drop the singleton + stop the scheduler."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    # ── Boot decision ────────────────────────────────────────────────────

    def start_if_primary(self, *, lock_path: str | None = None) -> bool:
        """Start the scheduler iff this process owns the primary lock.

        Returns ``True`` when the scheduler actually started here. Multi-
        worker deployments running gunicorn will only see one worker
        succeed; the rest see ``False`` and remain inert.
        """
        if self._scheduler.running:
            logger.info(
                "[scheduler] already running, next %s at %s",
                _JOB_ID, self._format_next_run() or "<not scheduled>",
            )
            return True

        target = Path(lock_path or self._default_lock_path())
        if not self._claim_lock(target):
            logger.info(
                "[scheduler] another process holds %s — skipping start in pid=%s",
                target, os.getpid(),
            )
            return False

        # Register the cron job + start.
        self._scheduler.add_job(
            self._snapshot_fn,
            CronTrigger(**self._cron_kwargs),
            id=_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info(
            "[scheduler] running, next %s at %s (pid=%s, lock=%s)",
            _JOB_ID, self._format_next_run() or "<not scheduled>",
            os.getpid(), target,
        )
        return True

    def shutdown(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
        finally:
            self._release_lock()

    # ── Public introspection ─────────────────────────────────────────────

    def status(self) -> dict:
        running = self._scheduler.running
        jobs = []
        if running:
            for job in self._scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "next_run_time": job.next_run_time.isoformat()
                        if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })
        return {
            "running": bool(running),
            "jobs": jobs,
            "pid": os.getpid(),
            "primary": self._lock_file is not None,
        }

    def next_run(self) -> str | None:
        return self._format_next_run()

    def run_now(self) -> Any:
        """Synchronous fire-now. Returns whatever the snapshot fn returns."""
        return self._snapshot_fn()

    # ── Internals ────────────────────────────────────────────────────────

    def _format_next_run(self) -> str | None:
        if not self._scheduler.running:
            return None
        job = self._scheduler.get_job(_JOB_ID)
        if not job or not job.next_run_time:
            return None
        return job.next_run_time.isoformat()

    @staticmethod
    def _default_lock_path() -> str:
        # Mirrors the auth secret/key directory so deployments that mount
        # /data have one consistent stateful directory.
        base = os.environ.get("STOCK_CONFIG_DIR") or str(Path.home() / ".stock_trading")
        Path(base).mkdir(parents=True, exist_ok=True)
        return str(Path(base) / "scheduler.lock")

    def _claim_lock(self, path: Path) -> bool:
        """Best-effort exclusive create of a small lock file.

        Returns True iff *we* created it. The file holds our pid + a
        scheduler-id timestamp so an operator can see which worker owns
        the job. Stale locks (older than 24h with the holder pid gone)
        are reclaimed.
        """
        # Reclaim stale locks when the holding pid is no longer alive.
        if path.exists():
            try:
                content = path.read_text().strip()
            except OSError:
                content = ""
            holder_pid = self._parse_pid(content)
            if holder_pid is not None and not _pid_alive(holder_pid):
                logger.info(
                    "[scheduler] reclaiming stale lock %s (dead pid=%s)",
                    path, holder_pid,
                )
                try:
                    path.unlink()
                except OSError:
                    return False

        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            from stock_trading_system.utils.timez import now_utc
            f.write(f"pid={os.getpid()} ts={now_utc().isoformat()}\n")
        self._lock_file = path
        return True

    def _release_lock(self) -> None:
        if self._lock_file is None:
            return
        path = self._lock_file
        self._lock_file = None
        # Only remove if we still own it (pid match).
        if not path.exists():
            return
        try:
            content = path.read_text().strip()
        except OSError:
            return
        if self._parse_pid(content) == os.getpid():
            try:
                path.unlink()
            except OSError:
                pass

    @staticmethod
    def _parse_pid(content: str) -> int | None:
        for token in content.split():
            if token.startswith("pid="):
                try:
                    return int(token.split("=", 1)[1])
                except ValueError:
                    return None
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't own it — treat as alive.
        return True
    except OSError:
        return False
    return True


# ── Snapshot driver used by the cron job ─────────────────────────────────────


def take_snapshot_all_users(
    user_repository,
    portfolio_manager_factory: Callable[[int], Any],
) -> dict:
    """Iterate every active user and call ``take_snapshot``.

    Decoupled from web/app.py wiring so it's testable on its own. Pass a
    callable that returns a per-user PortfolioManager — keeps the data-
    manager singleton story out of this module.

    Returns a per-user summary so /api/scheduler/run-now can echo what
    happened.
    """
    users = user_repository.list_active()
    results: list[dict] = []
    for user in users:
        pm = portfolio_manager_factory(user.id)
        pm.take_snapshot(user_id=user.id)
        results.append({
            "user_id": user.id,
            "email": getattr(user, "email", None),
            "ok": True,
        })
    from stock_trading_system.utils.timez import now_utc
    return {"ran_at": now_utc().isoformat(),
            "user_count": len(results),
            "results": results}
