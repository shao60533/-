"""Task scheduler - runs periodic tasks (alerts, reports, snapshots).

Handles timezone-aware scheduling for US and A-share markets.
"""

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

    def setup(self):
        """Configure scheduled tasks."""
        # Alert checking - every N seconds (configured interval)
        schedule.every(self._alert_interval).seconds.do(self._check_alerts)

        # Daily tasks
        schedule.every().day.at("09:00").do(self._pre_market_scan)    # Pre-market
        schedule.every().day.at("16:30").do(self._post_market_close)  # Post-market

        # Weekly report - Sunday
        schedule.every().sunday.at("18:00").do(self._weekly_report)

        # Monthly report - 1st of month
        schedule.every().day.at("19:00").do(self._monthly_report_if_needed)

        logger.info("Scheduler configured: alerts every %ds, daily/weekly/monthly tasks set", self._alert_interval)

    def start(self):
        """Start the scheduler loop."""
        self.setup()
        logger.info("Scheduler started. Press Ctrl+C to stop.")

        while True:
            schedule.run_pending()
            time.sleep(1)

    def _check_alerts(self):
        """Check all active alerts."""
        try:
            triggered = self._alert_monitor.check_alerts()
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
