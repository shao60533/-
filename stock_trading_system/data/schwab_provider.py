"""Schwab Trader API data provider — primary US realtime source.

OAuth 2.0 token-based access via schwab-py. Token is generated once via the
web OAuth flow (`/oauth/schwab/start` -> `/oauth/schwab/callback`) and persisted
to ``schwab.token_path``. schwab-py then auto-refreshes the access token.

Refresh-token expires every 7 days — the user must re-authorize via the web
flow before that. ``token_age_days`` is exposed for monitoring.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.schwab")

# Map our period strings to (start_datetime offset days, schwab method name)
_HISTORY_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 31, "3mo": 93, "6mo": 186,
    "1y": 366, "2y": 731, "5y": 1827,
}


class SchwabProvider:
    """Schwab Trader API data provider — US equities only."""

    def __init__(self, config: dict):
        sc = (config.get("schwab") or {})
        self._app_key = sc.get("app_key") or os.environ.get("SCHWAB_APP_KEY", "")
        self._app_secret = sc.get("app_secret") or os.environ.get(
            "SCHWAB_APP_SECRET", "")
        self._token_path = sc.get("token_path") or os.environ.get(
            "SCHWAB_TOKEN_PATH", "data/schwab_token.json")
        self._enabled_flag = bool(sc.get("enabled", False))
        self._client = None

    @property
    def enabled(self) -> bool:
        """True only if app key is set, token file exists, and config flag on."""
        if not self._enabled_flag:
            return False
        if not (self._app_key and self._app_secret):
            return False
        return Path(self._token_path).exists()

    def is_available(self) -> bool:
        return self.enabled

    def token_age_days(self) -> float | None:
        """Age of the token file in days; None if file missing."""
        try:
            mtime = Path(self._token_path).stat().st_mtime
            return (time.time() - mtime) / 86400.0
        except FileNotFoundError:
            return None

    def _get_client(self):
        if self._client is None:
            from schwab.auth import client_from_token_file
            self._client = client_from_token_file(
                token_path=self._token_path,
                api_key=self._app_key,
                app_secret=self._app_secret,
            )
        return self._client

    # ── Single-symbol quote ────────────────────────────────────────────

    def get_stock_price(self, ticker: str) -> dict | None:
        """Real-time quote for one symbol."""
        if not self.enabled:
            return None
        try:
            resp = self._get_client().get_quote(ticker)
            if resp.status_code != 200:
                logger.warning("Schwab get_quote(%s) HTTP %s",
                               ticker, resp.status_code)
                return None
            payload = resp.json() or {}
            symbol_block = payload.get(ticker) or payload.get(ticker.upper())
            if not symbol_block:
                return None
            return self._normalize_quote(ticker, symbol_block)
        except Exception as e:  # noqa: BLE001
            logger.error("Schwab get_stock_price(%s) failed: %s", ticker, e)
            return None

    # ── Batch quote (key performance path) ─────────────────────────────

    def get_stock_price_batch(self, tickers: list[str]) -> dict[str, dict]:
        """Batch quote — Schwab supports up to 500 symbols per call.

        Returns ``{ticker: quote_dict}``. Missing/invalid tickers are silently
        omitted; callers should use the original list as the canonical set.
        """
        if not (self.enabled and tickers):
            return {}
        symbols = [t.upper().strip() for t in tickers if t and t.strip()]
        if not symbols:
            return {}
        try:
            resp = self._get_client().get_quotes(symbols[:500])
            if resp.status_code != 200:
                logger.warning("Schwab get_quotes batch HTTP %s",
                               resp.status_code)
                return {}
            payload = resp.json() or {}
            result: dict[str, dict] = {}
            for sym in symbols:
                block = payload.get(sym)
                if block:
                    quote = self._normalize_quote(sym, block)
                    if quote:
                        result[sym] = quote
            return result
        except Exception as e:  # noqa: BLE001
            logger.error("Schwab get_stock_price_batch failed: %s", e)
            return {}

    # ── Historical bars ────────────────────────────────────────────────

    def get_stock_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame | None:
        """Daily/intraday OHLCV bars."""
        if not self.enabled:
            return None
        try:
            client = self._get_client()
            days_back = _HISTORY_PERIOD_DAYS.get(period, 366)
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days_back)

            if interval == "1d":
                resp = client.get_price_history_every_day(
                    ticker, start_datetime=start, end_datetime=end,
                )
            elif interval in ("1m", "1min"):
                resp = client.get_price_history_every_minute(
                    ticker, start_datetime=start, end_datetime=end,
                )
            elif interval in ("5m", "5min"):
                resp = client.get_price_history_every_five_minutes(
                    ticker, start_datetime=start, end_datetime=end,
                )
            elif interval in ("15m", "15min"):
                resp = client.get_price_history_every_fifteen_minutes(
                    ticker, start_datetime=start, end_datetime=end,
                )
            elif interval in ("1h", "30m"):
                resp = client.get_price_history_every_thirty_minutes(
                    ticker, start_datetime=start, end_datetime=end,
                )
            elif interval == "1wk":
                resp = client.get_price_history_every_week(
                    ticker, start_datetime=start, end_datetime=end,
                )
            else:
                resp = client.get_price_history_every_day(
                    ticker, start_datetime=start, end_datetime=end,
                )

            if resp.status_code != 200:
                logger.warning("Schwab price_history(%s) HTTP %s",
                               ticker, resp.status_code)
                return None
            payload = resp.json() or {}
            candles = payload.get("candles") or []
            if not candles:
                return None

            df = pd.DataFrame([{
                "date": pd.to_datetime(c["datetime"], unit="ms"),
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c.get("close"),
                "volume": c.get("volume"),
            } for c in candles])
            df.set_index("date", inplace=True)
            return df
        except Exception as e:  # noqa: BLE001
            logger.error("Schwab get_stock_history(%s) failed: %s", ticker, e)
            return None

    # ── Normalization ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_quote(ticker: str, block: dict) -> dict | None:
        """Schwab response → project quote schema.

        Schwab quote payload shape (per /marketdata/v1/quotes)::

            {"AAPL": {"symbol": "AAPL", "quote": {"lastPrice": ..., ...}, ...}}
        """
        q = block.get("quote") or {}
        last = q.get("lastPrice")
        close = q.get("closePrice")
        # If neither last nor close is present this row is unusable
        if last is None and close is None:
            return None
        return {
            "ticker": ticker,
            "last": last,
            "close": close,
            "open": q.get("openPrice"),
            "high": q.get("highPrice"),
            "low": q.get("lowPrice"),
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "volume": q.get("totalVolume"),
            "source": "schwab",
            "timestamp_ms": q.get("quoteTime"),
        }
