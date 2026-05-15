"""Polygon.io data provider - backup US market data source (free tier).

Free tier: 5 API calls/minute, delayed data.
Used when IB TWS is not available.
"""

import threading
import time
from datetime import datetime, timedelta

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.polygon")


class PolygonProvider:
    """Polygon.io data provider (free tier, 5 req/min)."""

    def __init__(self, config: dict):
        self._api_key = config.get("polygon", {}).get("api_key", "")
        self._client = None
        self._last_call = 0.0
        self._min_interval = 12.5  # 5 calls/min = 1 call per 12s
        # hardening-iteration-v1 P2.7: pre-P2.7 `_last_call` was unguarded;
        # PortfolioManager.get_holdings spawns 8 ThreadPoolExecutor workers
        # that all call _rate_limit concurrently — every worker reads the
        # stale timestamp, every worker decides "elapsed >= 12.5s", and
        # five requests fire in the same millisecond → 429 from Polygon.
        # The mutex enforces ONE caller at a time inside the sleep window.
        self._rl_lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            from polygon import RESTClient

            self._client = RESTClient(api_key=self._api_key)
        return self._client

    def _rate_limit(self):
        """Enforce rate limiting for free tier (thread-safe)."""
        with self._rl_lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def get_stock_price(self, ticker: str) -> dict | None:
        """Get previous close price (free tier doesn't have real-time)."""
        if not self.is_available():
            return None
        try:
            self._rate_limit()
            client = self._get_client()
            agg = client.get_previous_close_agg(ticker)
            if agg and len(agg) > 0:
                bar = agg[0]
                return {
                    "ticker": ticker,
                    "last": bar.close,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            return None
        except Exception as e:
            logger.error("Polygon get_stock_price(%s) failed: %s", ticker, e)
            return None

    def get_stock_history(
        self,
        ticker: str,
        from_date: str | None = None,
        to_date: str | None = None,
        timespan: str = "day",
    ) -> pd.DataFrame | None:
        """Get historical OHLCV data.

        Args:
            ticker: Stock symbol
            from_date: Start date YYYY-MM-DD (default: 1 year ago)
            to_date: End date YYYY-MM-DD (default: today)
            timespan: "day", "hour", "minute"
        """
        if not self.is_available():
            return None
        try:
            self._rate_limit()
            client = self._get_client()

            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            if not from_date:
                from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

            aggs = list(client.list_aggs(
                ticker=ticker,
                multiplier=1,
                timespan=timespan,
                from_=from_date,
                to=to_date,
                limit=50000,
            ))

            if not aggs:
                return None

            df = pd.DataFrame([{
                "date": datetime.fromtimestamp(a.timestamp / 1000),
                "open": a.open,
                "high": a.high,
                "low": a.low,
                "close": a.close,
                "volume": a.volume,
            } for a in aggs])

            df.set_index("date", inplace=True)
            return df
        except Exception as e:
            logger.error("Polygon get_stock_history(%s) failed: %s", ticker, e)
            return None

    def get_stock_news(self, ticker: str, limit: int = 10) -> list[dict]:
        """Get recent news for a stock."""
        if not self.is_available():
            return []
        try:
            self._rate_limit()
            client = self._get_client()
            news = list(client.list_ticker_news(ticker=ticker, limit=limit))
            return [
                {
                    "title": n.title,
                    "url": n.article_url,
                    "published": str(n.published_utc) if n.published_utc else "",
                    "source": n.publisher.name if n.publisher else "",
                }
                for n in news
            ]
        except Exception as e:
            logger.error("Polygon get_stock_news(%s) failed: %s", ticker, e)
            return []

    def search_tickers(self, query: str) -> list[dict]:
        """Search for tickers matching a query."""
        if not self.is_available():
            return []
        try:
            self._rate_limit()
            client = self._get_client()
            results = list(client.list_tickers(search=query, market="stocks", limit=10))
            return [
                {
                    "ticker": r.ticker,
                    "name": r.name,
                    "market": r.market,
                    "type": r.type,
                }
                for r in results
            ]
        except Exception as e:
            logger.error("Polygon search_tickers(%s) failed: %s", query, e)
            return []
