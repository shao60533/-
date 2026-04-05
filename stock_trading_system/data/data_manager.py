"""Unified data interface with automatic routing and failover.

- US stocks: IB TWS (primary) -> Polygon.io (backup) -> yfinance (fallback)
- A-shares: AkShare
"""

import pandas as pd

from stock_trading_system.data.ib_provider import IBProvider
from stock_trading_system.data.polygon_provider import PolygonProvider
from stock_trading_system.data.akshare_provider import AkShareProvider
from stock_trading_system.data.yfinance_provider import YFinanceProvider
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import detect_market

logger = get_logger("data.manager")


class DataManager:
    """Unified data manager with automatic market routing and failover."""

    def __init__(self, config: dict):
        self._config = config
        self._ib = IBProvider(config)
        self._polygon = PolygonProvider(config)
        self._akshare = AkShareProvider()
        self._yfinance = YFinanceProvider()

    def get_price(self, ticker: str, market: str | None = None) -> dict | None:
        """Get current price for a stock.

        Routing: US -> IB -> Polygon -> yfinance | CN -> AkShare
        """
        market = market or detect_market(ticker)

        if market == "cn":
            return self._akshare.get_stock_price(ticker)

        # US market fallback chain
        if self._config.get("ib", {}).get("enabled"):
            result = self._ib.get_stock_price(ticker)
            if result:
                return result
            logger.info("IB failed for %s, trying Polygon", ticker)

        result = self._polygon.get_stock_price(ticker)
        if result:
            return result
        logger.info("Polygon failed for %s, trying yfinance", ticker)

        return self._yfinance.get_stock_price(ticker)

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

        if market == "cn":
            return self._akshare.get_stock_history(ticker)

        # US market fallback chain
        if self._config.get("ib", {}).get("enabled"):
            # Convert period format for IB
            ib_duration = _period_to_ib_duration(period)
            ib_bar = _interval_to_ib_bar(interval)
            result = self._ib.get_stock_history(ticker, duration=ib_duration, bar_size=ib_bar)
            if result is not None:
                return result
            logger.info("IB history failed for %s, trying Polygon", ticker)

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
