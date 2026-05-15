"""Alert monitor - checks price/indicator conditions and triggers notifications."""

from datetime import datetime
from stock_trading_system.utils.timez import now_local, now_ny

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

    def add_alert(self, ticker: str, condition: str, threshold: float,
                   user_id: int | None = None):
        """Add a new alert.

        ``user_id`` scopes the alert so the listing/check API can return
        only this user's alerts. ``None`` is allowed for legacy callers
        but the dashboard / web layer always passes ``g.user.id``.
        """
        self._db.add_alert(ticker, condition, threshold, user_id=user_id)
        logger.info("Alert added: %s %s %s (user=%s)", ticker, condition, threshold, user_id)

    def remove_alert(self, alert_id: int, user_id: int) -> bool:
        """Remove an alert owned by ``user_id``. Returns True if a row was
        deleted, False if no such alert exists for this user.

        ``user_id`` is required as of hardening-iteration-v1 P0.3 — the
        former signature ``remove_alert(alert_id)`` was an IDOR vector
        (C4): any logged-in user could delete any other user's alerts by
        guessing the id.
        """
        deleted = self._db.remove_alert(alert_id, user_id=user_id)
        logger.info("Alert remove: id=%d user=%d deleted=%d",
                    alert_id, user_id, deleted)
        return deleted > 0

    def list_alerts(self, user_id: int | None = None,
                     scope: str = "user") -> list[dict]:
        """Return active alerts for a tenant.

        ``scope='user'`` (default) requires ``user_id`` and returns only
        that user's alerts — what the dashboard shows. ``scope='all'``
        returns every active alert and is reserved for the background
        scheduler / admin tooling.
        """
        if scope not in ("user", "all"):
            raise ValueError(f"scope must be 'user' or 'all', got {scope!r}")
        if scope == "user" and user_id is None:
            raise ValueError("scope='user' requires user_id")
        return self._db.get_active_alerts(
            user_id=None if scope == "all" else user_id,
        )

    def check_alerts(self, user_id: int | None = None,
                      scope: str = "all") -> list[dict]:
        """Check active alerts and return triggered ones.

        Default ``scope='all'`` matches the cron/scheduler path which
        evaluates every user's alerts in one pass. Web-triggered checks
        from a logged-in dashboard pass ``user_id=g.user.id``,
        ``scope='user'`` so users only retrigger their own alerts.
        """
        if scope not in ("user", "all"):
            raise ValueError(f"scope must be 'user' or 'all', got {scope!r}")
        if scope == "user" and user_id is None:
            raise ValueError("scope='user' requires user_id")
        alerts = self._db.get_active_alerts(
            user_id=None if scope == "all" else user_id,
        )
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
                        alert["id"], ticker, condition, threshold,
                        current_price, user_id=alert.get("user_id"),
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
                f"Time: {now_ny().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            for notifier in self._notifiers:
                try:
                    notifier.send(f"Stock Alert: {alert['ticker']}", message)
                except Exception as e:
                    logger.error("Notification failed: %s", e)

            # Always log to console
            logger.info(message)
