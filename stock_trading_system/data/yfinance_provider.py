"""yfinance data provider - fallback data source.

Free, no API key required. Covers US and some international stocks.
"""

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.yfinance")


class YFinanceProvider:
    """yfinance fallback data provider."""

    def get_stock_price(self, ticker: str) -> dict | None:
        """Get current price for a stock."""
        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
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
            import yfinance as yf

            stock = yf.Ticker(ticker)
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
            import yfinance as yf

            stock = yf.Ticker(ticker)
            return stock.info
        except Exception as e:
            logger.error("yfinance get_fundamentals(%s) failed: %s", ticker, e)
            return None

    def get_news(self, ticker: str) -> list[dict]:
        """Get recent news."""
        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
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
