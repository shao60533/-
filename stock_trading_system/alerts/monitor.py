"""Alert monitor - checks price/indicator conditions and triggers notifications."""

from datetime import datetime

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.utils import get_logger

logger = get_logger("alerts.monitor")


class AlertMonitor:
    """Monitors stock conditions and triggers alerts."""

    def __init__(self, config: dict):
        self._config = config
        db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
        self._db = PortfolioDatabase(db_path)
        self._data_manager = DataManager(config)
        self._notifiers = []
        self._init_notifiers()

    def _init_notifiers(self):
        """Initialize enabled notification channels."""
        alerts_cfg = self._config.get("alerts", {})

        tg_cfg = alerts_cfg.get("telegram", {})
        if tg_cfg.get("enabled") and tg_cfg.get("bot_token"):
            from stock_trading_system.alerts.telegram_notifier import TelegramNotifier
            self._notifiers.append(TelegramNotifier(tg_cfg))

        email_cfg = alerts_cfg.get("email", {})
        if email_cfg.get("enabled") and email_cfg.get("smtp_host"):
            from stock_trading_system.alerts.email_notifier import EmailNotifier
            self._notifiers.append(EmailNotifier(email_cfg))

    def add_alert(self, ticker: str, condition: str, threshold: float):
        """Add a new alert."""
        self._db.add_alert(ticker, condition, threshold)
        logger.info("Alert added: %s %s %s", ticker, condition, threshold)

    def remove_alert(self, alert_id: int):
        """Remove an alert by ID."""
        self._db.remove_alert(alert_id)
        logger.info("Alert removed: %d", alert_id)

    def list_alerts(self) -> list[dict]:
        """List all active alerts."""
        return self._db.get_active_alerts()

    def check_alerts(self) -> list[dict]:
        """Check all active alerts and return triggered ones."""
        alerts = self._db.get_active_alerts()
        triggered = []

        for alert in alerts:
            ticker = alert["ticker"]
            condition = alert["condition"]
            threshold = alert["threshold"]

            try:
                price_data = self._data_manager.get_price(ticker)
                if not price_data:
                    continue

                current_price = price_data.get("last") or price_data.get("close") or 0
                if current_price == 0:
                    continue

                is_triggered = self._evaluate_condition(
                    condition, threshold, current_price, price_data
                )

                if is_triggered:
                    alert["current_price"] = current_price
                    triggered.append(alert)
                    self._db.trigger_alert(alert["id"])
                    self._db.save_alert_trigger(
                        alert["id"], ticker, condition, threshold, current_price
                    )
                    logger.info(
                        "Alert triggered: %s %s %s (current: %s)",
                        ticker, condition, threshold, current_price,
                    )
            except Exception as e:
                logger.error("Error checking alert for %s: %s", ticker, e)

        # Send notifications for triggered alerts
        if triggered:
            self._notify(triggered)

        return triggered

    def _evaluate_condition(
        self, condition: str, threshold: float, current_price: float, price_data: dict
    ) -> bool:
        """Evaluate if alert condition is met."""
        if condition == "price_above":
            return current_price >= threshold
        elif condition == "price_below":
            return current_price <= threshold
        elif condition == "pct_change_above":
            close = price_data.get("close", current_price)
            if close > 0:
                pct = ((current_price - close) / close) * 100
                return pct >= threshold
        elif condition == "pct_change_below":
            close = price_data.get("close", current_price)
            if close > 0:
                pct = ((current_price - close) / close) * 100
                return pct <= -threshold
        elif condition == "volume_spike":
            volume = price_data.get("volume", 0)
            return volume >= threshold
        elif condition == "stop_loss":
            return current_price <= threshold
        elif condition == "take_profit":
            return current_price >= threshold
        return False

    def _notify(self, triggered_alerts: list[dict]):
        """Send notifications for triggered alerts."""
        for alert in triggered_alerts:
            message = (
                f"🚨 Alert Triggered: {alert['ticker']}\n"
                f"Condition: {alert['condition']} {alert['threshold']}\n"
                f"Current Price: {alert.get('current_price', 'N/A')}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            for notifier in self._notifiers:
                try:
                    notifier.send(f"Stock Alert: {alert['ticker']}", message)
                except Exception as e:
                    logger.error("Notification failed: %s", e)

            # Always log to console
            logger.info(message)
