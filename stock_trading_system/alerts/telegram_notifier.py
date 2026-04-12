"""Telegram notification sender."""

import asyncio

from stock_trading_system.utils import get_logger

logger = get_logger("alerts.telegram")


class TelegramNotifier:
    """Send notifications via Telegram Bot."""

    def __init__(self, config: dict):
        self._token = config.get("bot_token", "")
        self._chat_id = config.get("chat_id", "")

    def send(self, subject: str, message: str):
        """Send a message via Telegram."""
        if not self._token or not self._chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return

        try:
            asyncio.run(self._send_async(subject, message))
        except RuntimeError:
            # If event loop already running, create a new one
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._send_async(subject, message))
            loop.close()

    async def _send_async(self, subject: str, message: str):
        from telegram import Bot

        bot = Bot(token=self._token)
        text = f"*{subject}*\n\n{message}"
        await bot.send_message(
            chat_id=self._chat_id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Telegram notification sent: %s", subject)
