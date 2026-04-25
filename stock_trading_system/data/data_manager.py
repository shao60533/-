"""Unified data interface with automatic routing and failover.

- US stocks: IB TWS (primary) -> Polygon.io (backup) -> yfinance -> Qwen (last resort)
- A-shares: AkShare -> Qwen (last resort)
"""

import pandas as pd

from stock_trading_system.data.ib_provider import IBProvider
from stock_trading_system.data.polygon_provider import PolygonProvider
from stock_trading_system.data.akshare_provider import AkShareProvider
from stock_trading_system.data.yfinance_provider import YFinanceProvider
from stock_trading_system.data.qwen_provider import QwenProvider
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import detect_market

logger = get_logger("data.manager")


class DataManager:
    """Unified data manager with automatic market routing and failover."""

    # Consecutive failure threshold — skip provider after N failures
    _SKIP_THRESHOLD = 1

    def __init__(self, config: dict):
        self._config = config
        self._ib = IBProvider(config)
        self._polygon = PolygonProvider(config)
        self._akshare = AkShareProvider()
        self._yfinance = YFinanceProvider()
        self._qwen = QwenProvider(config)
        # Track consecutive failures per provider to skip broken ones.
        # IB starts skipped (event loop issue in thread pools).
        # Polygon starts skipped (free tier 429 rate limit makes it
        # unusable for concurrent batch lookups like get_holdings).
        # Both auto-reset on first successful call from other code paths.
        self._fail_count = {"ib": 1, "polygon": 1}

    def _is_skipped(self, provider: str) -> bool:
        return self._fail_count.get(provider, 0) >= self._SKIP_THRESHOLD

    def _record_fail(self, provider: str):
        self._fail_count[provider] = self._fail_count.get(provider, 0) + 1

    def _record_success(self, provider: str):
        self._fail_count[provider] = 0

    def get_price(self, ticker: str, market: str | None = None) -> dict | None:
        """Get current price for a stock.

        Routing:
          US -> IB -> Polygon -> yfinance -> Qwen
          CN -> AkShare -> Qwen

        Providers that fail consecutively are auto-skipped to avoid
        slow timeout cascades (e.g. Polygon 429 rate limit).
        """
        market = market or detect_market(ticker)

        if market == "cn":
            result = self._akshare.get_stock_price(ticker)
            if result:
                return result
            if self._qwen.enabled:
                logger.info("AkShare failed for %s, trying Qwen (last resort)", ticker)
                return self._qwen.get_stock_price(ticker)
            return None

        providers = self._config.get("providers", {}) or {}
        ib_master = providers.get("ib_enabled", True)
        polygon_master = providers.get("polygon_enabled", True)

        # US market fallback chain (with auto-skip for broken providers)
        if (ib_master and self._config.get("ib", {}).get("enabled")
                and not self._is_skipped("ib")):
            result = self._ib.get_stock_price(ticker)
            if result:
                self._record_success("ib")
                return result
            self._record_fail("ib")
            if self._is_skipped("ib"):
                logger.info("IB skipped (consecutive failures) — falling through to yfinance")

        if polygon_master and not self._is_skipped("polygon"):
            result = self._polygon.get_stock_price(ticker)
            if result:
                self._record_success("polygon")
                return result
            self._record_fail("polygon")
            if self._is_skipped("polygon"):
                logger.info("Polygon skipped (rate limited) — falling through to yfinance")

        result = self._yfinance.get_stock_price(ticker)
        if result:
            return result

        if self._qwen.enabled:
            logger.info("yfinance failed for %s, trying Qwen (last resort)", ticker)
            return self._qwen.get_stock_price(ticker)

        return None

    def get_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        market: str | None = None,
    ) -> pd.DataFrame | None:
        """Get historical OHLCV data.

        Args:
            ticker: Stock symbol
            period: "1d", "5d", "1mo", "3mo", "6mo", "1y"
            interval: "1d", "1h", "5m"
            market: "us" or "cn", auto-detected if None
        """
        market = market or detect_market(ticker)
        providers = self._config.get("providers", {}) or {}

        if market == "cn":
            return self._akshare.get_stock_history(ticker)

        # US market fallback chain (gated by master switches)
        if (providers.get("ib_enabled", True)
                and self._config.get("ib", {}).get("enabled")):
            ib_duration = _period_to_ib_duration(period)
            ib_bar = _interval_to_ib_bar(interval)
            result = self._ib.get_stock_history(ticker, duration=ib_duration, bar_size=ib_bar)
            if result is not None:
                return result
            logger.info("IB history failed for %s, trying Polygon", ticker)

        if providers.get("polygon_enabled", True):
            result = self._polygon.get_stock_history(ticker)
            if result is not None:
                return result
            logger.info("Polygon history failed for %s, trying yfinance", ticker)

        return self._yfinance.get_stock_history(ticker, period=period, interval=interval)

    def get_fundamentals(self, ticker: str, market: str | None = None) -> dict | None:
        """Get fundamental data."""
        market = market or detect_market(ticker)

        if market == "cn":
            return self._akshare.get_fundamentals(ticker)

        # US: try yfinance first (richest free fundamentals), then IB
        result = self._yfinance.get_fundamentals(ticker)
        if result:
            return result

        if self._config.get("ib", {}).get("enabled"):
            return self._ib.get_fundamentals(ticker)

        return None

    def get_news(self, ticker: str, market: str | None = None) -> list[dict]:
        """Get recent news."""
        market = market or detect_market(ticker)

        if market == "cn":
            return self._akshare.get_news(ticker)

        # US: try Polygon first (better news), then yfinance
        news = self._polygon.get_stock_news(ticker)
        if news:
            return news
        return self._yfinance.get_news(ticker)

    def get_ib_provider(self) -> IBProvider:
        """Get IB provider directly (for scanner, subscriptions, etc.)."""
        return self._ib

    def get_qwen_provider(self) -> QwenProvider:
        """Get Qwen provider directly (for AI-powered screening)."""
        return self._qwen

    def disconnect(self):
        """Disconnect all providers."""
        self._ib.disconnect()


def _period_to_ib_duration(period: str) -> str:
    """Convert period string to IB duration format."""
    mapping = {
        "1d": "1 D", "5d": "5 D", "1mo": "1 M",
        "3mo": "3 M", "6mo": "6 M", "1y": "1 Y",
        "2y": "2 Y", "5y": "5 Y",
    }
    return mapping.get(period, "1 Y")


def _interval_to_ib_bar(interval: str) -> str:
    """Convert interval string to IB bar size format."""
    mapping = {
        "1m": "1 min", "5m": "5 mins", "15m": "15 mins",
        "1h": "1 hour", "1d": "1 day", "1wk": "1 week",
    }
    return mapping.get(interval, "1 day")
