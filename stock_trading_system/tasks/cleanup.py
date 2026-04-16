"""Background task-record cleanup — purges old `tasks` rows on a schedule.

Why this exists:
- Task records accumulate forever otherwise (analysis, screen, backtest, etc.).
- On Railway with a small Persistent Volume, that's bad news within weeks.
- Config: `tasks.retention_days` (default 30) + `tasks.cleanup_interval` (6h).
- A daemon thread does periodic purges; safe to enable in any environment.
"""

from __future__ import annotations

import threading
import time

from stock_trading_system.tasks.task_store import TaskStore
from stock_trading_system.utils import get_logger

logger = get_logger("tasks.cleanup")


class TaskCleanupScheduler:
    """Daemon thread that periodically purges old task records.

    Also runs LocalCache.cleanup() on the same cadence to evict expired
    cache rows (they would be ignored on read anyway, but cleanup keeps
    SQLite file size bounded).
    """

    def __init__(
        self,
        store: TaskStore,
        retention_days: int = 30,
        interval_seconds: int = 6 * 3600,
        cache=None,
    ):
        self._store = store
        self._retention_days = max(1, int(retention_days))
        self._interval = max(60, int(interval_seconds))
        self._cache = cache
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="task-cleanup", daemon=True,
        )
        self._thread.start()
        logger.info(
            "Task cleanup scheduler started "
            "(retention=%dd, interval=%ds, cache=%s)",
            self._retention_days, self._interval, bool(self._cache),
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def run_once(self) -> dict:
        """Synchronous one-shot cleanup. Returns counts removed."""
        try:
            tasks_deleted = self._store.cleanup_expired(days=self._retention_days)
        except Exception as e:  # noqa: BLE001
            logger.warning("Task cleanup failed: %s", e)
            tasks_deleted = -1

        cache_deleted = -1
        if self._cache is not None:
            try:
                cache_deleted = self._cache.cleanup()
            except Exception as e:  # noqa: BLE001
                logger.warning("Cache cleanup failed: %s", e)

        if tasks_deleted >= 0 or cache_deleted >= 0:
            logger.info(
                "Cleanup tick: %d task rows + %d cache entries removed",
                max(tasks_deleted, 0), max(cache_deleted, 0),
            )
        return {"tasks_deleted": tasks_deleted, "cache_deleted": cache_deleted}

    def _run(self) -> None:
        # Run a first pass at startup, then on the interval.
        self.run_once()
        while not self._stop.is_set():
            # Wake on stop signal too — avoids waiting 6h to shut down.
            if self._stop.wait(self._interval):
                break
            self.run_once()
