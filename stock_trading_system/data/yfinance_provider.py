"""yfinance data provider - fallback data source.

Free, no API key required. Covers US and some international stocks.
"""

import threading

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.yfinance")


class YFinanceProvider:
    """yfinance fallback data provider.

    Reuses one curl_cffi Session per thread (curl handles are not
    thread-safe). This eliminates per-call TLS handshakes and prevents
    CLOSE_WAIT socket leaks under concurrent bundle preparation.
    """

    def __init__(self):
        self._tls = threading.local()

    def _session(self):
        sess = getattr(self._tls, "session", None)
        if sess is not None:
            return sess
        try:
            from curl_cffi import requests as cffi_requests
            sess = cffi_requests.Session(impersonate="chrome120")
        except Exception as e:
            logger.debug("curl_cffi session unavailable, using yfinance default: %s", e)
            sess = None
        self._tls.session = sess
        return sess

    def _ticker(self, symbol: str):
        import yfinance as yf
        sess = self._session()
        return yf.Ticker(symbol, session=sess) if sess is not None else yf.Ticker(symbol)

    def get_stock_price(self, ticker: str) -> dict | None:
        """Get current price for a stock."""
        try:
            stock = self._ticker(ticker)
            info = stock.fast_info

            return {
                "ticker": ticker,
                "last": info.last_price,
                "open": info.open,
                "high": info.day_high,
                "low": info.day_low,
                "close": info.previous_close,
                "volume": info.last_volume,
                "market_cap": info.market_cap,
            }
        except Exception as e:
            logger.error("yfinance get_stock_price(%s) failed: %s", ticker, e)
            return None

    def get_stock_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame | None:
        """Get historical OHLCV data.

        Args:
            ticker: Stock symbol
            period: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
            interval: "1m", "5m", "15m", "1h", "1d", "1wk", "1mo"
        """
        try:
            stock = self._ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df is None or df.empty:
                return None

            df.index.name = "date"
            df.columns = [c.lower() for c in df.columns]
            return df[["open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error("yfinance get_stock_history(%s) failed: %s", ticker, e)
            return None

    def get_fundamentals(self, ticker: str) -> dict | None:
        """Get fundamental data."""
        try:
            stock = self._ticker(ticker)
            return stock.info
        except Exception as e:
            logger.error("yfinance get_fundamentals(%s) failed: %s", ticker, e)
            return None

    def get_news(self, ticker: str) -> list[dict]:
        """Get recent news."""
        try:
            stock = self._ticker(ticker)
            raw = stock.news or []
            results = []
            for n in raw[:20]:
                # yfinance >= 0.2.36 uses {id, content: {title, ...}}
                if "content" in n and isinstance(n["content"], dict):
                    c = n["content"]
                    url = ""
                    if "canonicalUrl" in c:
                        url = c["canonicalUrl"].get("url", "") if isinstance(c["canonicalUrl"], dict) else str(c["canonicalUrl"])
                    elif "clickThroughUrl" in c:
                        url = c["clickThroughUrl"].get("url", "") if isinstance(c["clickThroughUrl"], dict) else str(c["clickThroughUrl"])
                    pub_date = c.get("pubDate", "")
                    provider = c.get("provider", {})
                    source = provider.get("displayName", "") if isinstance(provider, dict) else str(provider)
                    results.append({
                        "title": c.get("title", ""),
                        "url": url,
                        "published": str(pub_date),
                        "source": source,
                    })
                else:
                    # Legacy format
                    results.append({
                        "title": n.get("title", ""),
                        "url": n.get("link", ""),
                        "published": str(n.get("providerPublishTime", "")),
                        "source": n.get("publisher", ""),
                    })
            return results
        except Exception as e:
            logger.error("yfinance get_news(%s) failed: %s", ticker, e)
            return []
