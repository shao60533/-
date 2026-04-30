"""Task scheduler - runs periodic tasks (alerts, reports, snapshots).

Handles timezone-aware scheduling for US and A-share markets.
"""

import threading
import time
from datetime import datetime

import schedule

from stock_trading_system.alerts.monitor import AlertMonitor
from stock_trading_system.portfolio.manager import PortfolioManager
from stock_trading_system.reports.report_generator import ReportGenerator
from stock_trading_system.utils import get_logger

logger = get_logger("scheduler")


class TaskScheduler:
    """Periodic task scheduler for the trading system."""

    def __init__(self, config: dict):
        self._config = config
        self._alert_monitor = AlertMonitor(config)
        self._portfolio_manager = PortfolioManager(config)
        self._report_generator = ReportGenerator(config)
        self._alert_interval = config.get("alerts", {}).get("check_interval", 60)
        self._stop_event = threading.Event()
        self._jobs: list = []

    @property
    def is_running(self) -> bool:
        """Whether the scheduler loop is currently active."""
        return not self._stop_event.is_set() and bool(self._jobs)

    def setup(self):
        """Configure scheduled tasks."""
        # Clear any previous jobs so setup() is idempotent
        for job in self._jobs:
            schedule.cancel_job(job)
        self._jobs = []

        # Alert checking - every N seconds (configured interval)
        self._jobs.append(schedule.every(self._alert_interval).seconds.do(self._check_alerts))

        # Daily tasks
        self._jobs.append(schedule.every().day.at("09:00").do(self._pre_market_scan))    # Pre-market
        self._jobs.append(schedule.every().day.at("16:30").do(self._post_market_close))  # Post-market

        # Weekly report - Sunday
        self._jobs.append(schedule.every().sunday.at("18:00").do(self._weekly_report))

        # Monthly report - 1st of month
        self._jobs.append(schedule.every().day.at("19:00").do(self._monthly_report_if_needed))

        logger.info("Scheduler configured: alerts every %ds, daily/weekly/monthly tasks set", self._alert_interval)

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

    def _pre_market_scan(self):
        """Pre-market: analyze held stocks for the day ahead."""
        logger.info("Running pre-market scan...")
        try:
            holdings = self._portfolio_manager.get_holdings()
            if holdings:
                logger.info("Pre-market: %d positions to monitor today", len(holdings))
                for h in holdings:
                    logger.info("  %s: %s shares @ %s", h["ticker"], h["shares"], h["avg_cost"])
        except Exception as e:
            logger.error("Pre-market scan failed: %s", e)

    def _post_market_close(self):
        """Post-market: take snapshot and generate daily report."""
        logger.info("Running post-market tasks...")
        try:
            # Take daily snapshot
            self._portfolio_manager.take_snapshot()

            # Generate daily report
            report = self._report_generator.daily_report()
            logger.info("Daily report generated (%d chars)", len(report))

            # Send notifications
            self._notify_report("每日报告", report)
        except Exception as e:
            logger.error("Post-market tasks failed: %s", e)

        # Paper-trade EOD snapshot (best-effort)
        try:
            self._paper_trade_eod()
        except Exception as e:
            logger.error("Paper-trade EOD failed: %s", e)

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

    def _weekly_report(self):
        """Generate and send weekly report."""
        logger.info("Generating weekly report...")
        try:
            report = self._report_generator.weekly_report()
            self._notify_report("周报", report)
        except Exception as e:
            logger.error("Weekly report failed: %s", e)

    def _monthly_report_if_needed(self):
        """Generate monthly report on the 1st of each month."""
        if datetime.now().day == 1:
            logger.info("Generating monthly report...")
            try:
                report = self._report_generator.monthly_report()
                self._notify_report("月报", report)
            except Exception as e:
                logger.error("Monthly report failed: %s", e)

    def _notify_report(self, title: str, content: str):
        """Send report through configured notification channels."""
        for notifier in self._alert_monitor._notifiers:
            try:
                notifier.send(title, content[:4000])  # Truncate for message limits
            except Exception as e:
                logger.error("Report notification failed: %s", e)
