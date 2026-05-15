"""Task scheduler - alert checker + paper-trade EOD updater.

hardening-iteration-v1 P1.2 [C9]: this scheduler used to also call
``portfolio.take_snapshot()`` and ``ReportGenerator.daily_report()``
in cron context — neither path took a user_id, so snapshots landed
with ``user_id=NULL`` and the daily report aggregated every tenant's
data into one mass email. The per-user equivalent now lives in
``DailySnapshotScheduler.take_snapshot_all_users`` (APScheduler) and
in user-triggered ``/api/portfolio/snapshot`` calls. This class is
reduced to: (a) ``_check_alerts(scope='all')`` — the one legitimate
cross-tenant cron path, alerts are owned but eval is scheduled
globally — and (b) paper-trade EOD updates which are per-session
(session table is multi-tenant; the updater never needs a user_id).
"""

import threading
import time

import schedule

from stock_trading_system.alerts.monitor import AlertMonitor
from stock_trading_system.utils import get_logger

logger = get_logger("scheduler")


class TaskScheduler:
    """Periodic task scheduler for the trading system."""

    def __init__(self, config: dict):
        self._config = config
        self._alert_monitor = AlertMonitor(config)
        self._alert_interval = config.get("alerts", {}).get("check_interval", 60)
        self._stop_event = threading.Event()
        self._jobs: list = []

    @property
    def is_running(self) -> bool:
        """Whether the scheduler loop is currently active."""
        return not self._stop_event.is_set() and bool(self._jobs)

    def setup(self):
        """Configure scheduled tasks.

        Two jobs only after P1.2:
            - Alert evaluation every N seconds (scope='all' — alerts
              themselves carry user_id, eval is a single cross-tenant pass).
            - Paper-trade EOD at 16:30 ET (per-session; the session table
              is multi-tenant so the updater never needs a user_id).

        Snapshots and daily/weekly/monthly reports are intentionally NOT
        scheduled here — they belong to DailySnapshotScheduler (per-user
        APScheduler job) or user-triggered API calls. See the module
        docstring for why.
        """
        for job in self._jobs:
            schedule.cancel_job(job)
        self._jobs = []

        self._jobs.append(schedule.every(self._alert_interval).seconds.do(self._check_alerts))
        self._jobs.append(schedule.every().day.at("16:30").do(self._paper_trade_eod))

        logger.info(
            "Scheduler configured: alerts every %ds + paper-trade EOD at 16:30",
            self._alert_interval,
        )

    def start(self):
        """Start the scheduler loop (blocking)."""
        self.setup()
        self._stop_event.clear()
        logger.info("Scheduler started. Press Ctrl+C to stop.")

        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

        logger.info("Scheduler stopped.")

    def stop(self):
        """Signal the scheduler loop to exit and cancel registered jobs."""
        self._stop_event.set()
        for job in self._jobs:
            schedule.cancel_job(job)
        self._jobs = []
        logger.info("Scheduler stop requested.")

    def _check_alerts(self):
        """Check all active alerts across every tenant.

        The cron path is the only caller that legitimately spans users —
        it evaluates everyone's alerts in one pass and dispatches
        notifications to each owner. Web/dashboard checks scope to the
        current user instead.
        """
        try:
            triggered = self._alert_monitor.check_alerts(scope="all")
            if triggered:
                logger.info("%d alerts triggered", len(triggered))
        except Exception as e:
            logger.error("Alert check failed: %s", e)

    def _paper_trade_eod(self):
        """Update daily_stats for every ticker session."""
        from stock_trading_system.strategy.paper_trader import (
            PaperTradeStore, DailyUpdater,
        )
        db_path = self._config.get("portfolio", {}).get("db_path", "data/portfolio.db")
        store = PaperTradeStore(db_path)
        sessions = store.list_ticker_sessions()
        if not sessions:
            logger.info("Paper-trade EOD: no ticker sessions")
            return
        updater = DailyUpdater(self._config, store)
        updated = 0
        for sess in sessions:
            try:
                rows = updater.update_session(int(sess["id"]))
                if rows:
                    updated += 1
                    logger.info("Paper-trade EOD %s: +%d daily rows",
                                sess["ticker"], len(rows))
            except Exception as e:
                logger.warning("EOD update failed for %s: %s",
                               sess.get("ticker"), e)
        logger.info("Paper-trade EOD complete: %d/%d sessions updated",
                    updated, len(sessions))

