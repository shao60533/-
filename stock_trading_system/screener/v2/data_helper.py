"""Shared data helpers for V2 screening agents.

Avoids duplicating yfinance/qwen calls across agents by providing cached,
batch-friendly data accessors.
"""

from __future__ import annotations

import pandas as pd
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v2.data")


class DataHelper:
    """Shared data accessor with LocalCache awareness."""

    def __init__(self, config: dict, local_cache=None):
        self._config = config
        self._cache = local_cache

    # ── Price bars (used by Momentum / Technical / RegimeRelative) ──

    def get_bars(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
        """Get OHLCV bars with local cache. Falls back to yfinance."""
        if self._cache is not None:
            cached = self._cache.get_bars(ticker, period, interval)
            if cached is not None and not (hasattr(cached, "empty") and cached.empty):
                return cached
        try:
            import yfinance as yf
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
            if df is None or df.empty:
                return None
            if self._cache is not None:
                try:
                    self._cache.set_bars(ticker, period, interval, df)
                except Exception:
                    pass
            return df
        except Exception as e:  # noqa: BLE001
            logger.warning("yfinance bars failed for %s: %s", ticker, e)
            return None

    # ── Fundamentals ──

    def get_fundamentals(self, ticker: str) -> dict | None:
        """Get fundamentals dict (try cache → yfinance info)."""
        if self._cache is not None:
            cached = self._cache.get_fundamentals(ticker)
            if cached:
                return cached
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            f = {
                "ticker": ticker,
                "market_cap": info.get("marketCap"),
                "pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb": info.get("priceToBook"),
                "peg": info.get("pegRatio"),
                "roe": info.get("returnOnEquity"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "free_cashflow": info.get("freeCashflow"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "beta": info.get("beta"),
                "dividend_yield": info.get("dividendYield"),
                "short_ratio": info.get("shortRatio"),
                "short_percent_of_float": info.get("shortPercentOfFloat"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "short_name": info.get("shortName") or info.get("longName") or ticker,
            }
            if self._cache is not None:
                try:
                    self._cache.set_fundamentals(ticker, f)
                except Exception:
                    pass
            return f
        except Exception as e:  # noqa: BLE001
            logger.warning("yfinance fundamentals failed for %s: %s", ticker, e)
            return None

    # ── Utility math ──

    @staticmethod
    def pct_change(series: pd.Series, n: int) -> float | None:
        """Return n-period pct change as float (0.15 = +15%) or None."""
        try:
            if len(series) <= n:
                return None
            return float(series.iloc[-1] / series.iloc[-n - 1] - 1)
        except Exception:
            return None

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> float | None:
        """Classic RSI."""
        try:
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            rs = gain / loss.replace(0, 1e-10)
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
        except Exception:
            return None
