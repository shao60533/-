"""Email notification sender."""

import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from stock_trading_system.utils import get_logger

logger = get_logger("alerts.email")


class EmailNotifier:
    """Send notifications via email (SMTP)."""

    def __init__(self, config: dict):
        self._host = config.get("smtp_host", "")
        self._port = config.get("smtp_port", 587)
        self._username = config.get("username", "")
        self._password = config.get("password", "")
        self._to = config.get("to_address", "")

    def send(self, subject: str, message: str):
        """Send an email notification."""
        if not all([self._host, self._username, self._password, self._to]):
            logger.warning("Email not configured, skipping notification")
            return

        try:
            asyncio.run(self._send_async(subject, message))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._send_async(subject, message))
            loop.close()

    async def _send_async(self, subject: str, message: str):
        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Stock Alert] {subject}"
        msg["From"] = self._username
        msg["To"] = self._to

        # Plain text
        msg.attach(MIMEText(message, "plain"))

        # HTML version
        html = f"""
        <html><body>
        <h2>{subject}</h2>
        <pre>{message}</pre>
        <hr>
        <p><em>Stock Trading Advisory System</em></p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=True,
        )
        logger.info("Email notification sent to %s: %s", self._to, subject)
