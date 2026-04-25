"""Unified data router — Qwen-first with yfinance/AkShare fallback + cache.

Replaces the direct provider-chain in DataManager for *Qwen-friendly* data
types (price, fundamentals, news). Historical OHLCV for backtest is NEVER
routed through Qwen — see architecture proposal §4.4.3.

Routing table (when `data_routing.primary = "qwen"`):

  get_price(ticker):
    cache hit  -> return
    Qwen       -> validate_quote -> cache + return (success)
    yfinance   -> cache + return  (US fallback)
    AkShare    -> cache + return  (CN fallback)
    None

  get_fundamentals(ticker):
    cache hit  -> return
    Qwen       -> validate_fundamentals -> cache + return
    yfinance   -> cache + return  (US)
    AkShare    -> cache + return  (CN)
    None

  get_news(ticker):
    cache hit  -> return
    Qwen       -> validate_news -> cache + return
    yfinance   -> cache + return  (US)
    AkShare    -> cache + return  (CN)
    []

  get_history_for_backtest(ticker, period, interval):
    cache hit  -> return
    yfinance / AkShare  (never Qwen)
    None
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from stock_trading_system.data.akshare_provider import AkShareProvider
from stock_trading_system.data.local_cache import LocalCache
from stock_trading_system.data.qwen_provider import QwenProvider
from stock_trading_system.data.validators import (
    validate_fundamentals, validate_news, validate_quote,
)
from stock_trading_system.data.yfinance_provider import YFinanceProvider
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import detect_market

logger = get_logger("data.router")


class DataRouter:
    """Qwen-first data router with local fallback and SQLite caching."""

    def __init__(
        self,
        config: dict,
        qwen: QwenProvider | None = None,
        yfinance: YFinanceProvider | None = None,
        akshare: AkShareProvider | None = None,
        cache: LocalCache | None = None,
    ):
        self._config = config
        routing = (config.get("data_routing") or {})
        self._primary = routing.get("primary", "qwen")
        self._enable_cache = bool(routing.get("enable_cache", True))
        providers = (config.get("providers") or {})
        self._yf_enabled = providers.get("yfinance_enabled", True)
        self._akshare_enabled = providers.get("akshare_enabled", True)

        self._qwen = qwen or QwenProvider(config)
        self._yfinance = yfinance or YFinanceProvider()
        self._akshare = akshare or AkShareProvider()
        self._cache = cache  # injected from web layer; may be None in tests

    # ── Price ────────────────────────────────────────────────────────────

    def get_price(self, ticker: str, market: str | None = None) -> dict | None:
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return None
        market = market or detect_market(ticker)

        cached = self._cache_get("price_quote", ticker)
        if cached is not None:
            return cached

        # Primary: Qwen
        if self._primary == "qwen" and self._qwen.enabled:
            q = self._qwen.get_stock_price(ticker)
            q = validate_quote(q)
            if q:
                self._cache_set("price_quote", ticker, q)
                return q
            logger.info("Qwen price miss for %s — falling back", ticker)

        # Fallback chain
        q = self._fallback_price(ticker, market)
        if q is not None:
            self._cache_set("price_quote", ticker, q)
        return q

    def _fallback_price(self, ticker: str, market: str) -> dict | None:
        if market == "cn" and self._akshare_enabled:
            q = validate_quote(self._akshare.get_stock_price(ticker))
            if q:
                return q
        if self._yf_enabled:
            q = validate_quote(self._yfinance.get_stock_price(ticker))
            if q:
                return q
        # Last-ditch Qwen for US when primary=local
        if self._primary != "qwen" and self._qwen.enabled:
            return validate_quote(self._qwen.get_stock_price(ticker))
        return None

    # ── Fundamentals ─────────────────────────────────────────────────────

    def get_fundamentals(self, ticker: str) -> dict | None:
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return None
        market = detect_market(ticker)

        cached = self._cache_get("fundamentals", ticker)
        if cached is not None:
            return cached

        if self._primary == "qwen" and self._qwen.enabled:
            data = self._qwen.get_fundamentals(ticker)
            data = validate_fundamentals(data)
            if data:
                self._cache_set("fundamentals", ticker, data)
                return data
            logger.info("Qwen fundamentals miss for %s — falling back", ticker)

        data = self._fallback_fundamentals(ticker, market)
        if data is not None:
            self._cache_set("fundamentals", ticker, data)
        return data

    def _fallback_fundamentals(self, ticker: str, market: str) -> dict | None:
        if market == "cn" and self._akshare_enabled:
            return self._akshare.get_fundamentals(ticker)
        if self._yf_enabled:
            return self._yfinance.get_fundamentals(ticker)
        return None

    # ── News ─────────────────────────────────────────────────────────────

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return []
        market = detect_market(ticker)

        cached = self._cache_get("news", ticker)
        if cached is not None:
            return cached

        if self._primary == "qwen" and self._qwen.enabled:
            items = self._qwen.get_news(ticker, limit=limit)
            items = validate_news(items)
            if items:
                self._cache_set("news", ticker, items)
                return items
            logger.info("Qwen news miss for %s — falling back", ticker)

        items = self._fallback_news(ticker, market)
        items = validate_news(items)
        if items:
            self._cache_set("news", ticker, items)
        return items or []

    def _fallback_news(self, ticker: str, market: str) -> list[dict]:
        if market == "cn" and self._akshare_enabled:
            return self._akshare.get_news(ticker) or []
        if self._yf_enabled:
            return self._yfinance.get_news(ticker) or []
        return []

    # ── History (NEVER via Qwen) ─────────────────────────────────────────

    def get_history_for_backtest(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        market: str | None = None,
    ) -> pd.DataFrame | None:
        """Historical OHLCV for backtest. Always uses structured data source.

        Qwen is deliberately excluded — accuracy and reproducibility of
        250+ bar series cannot be guaranteed by an LLM.
        """
        ticker = (ticker or "").upper().strip()
        if not ticker:
            return None
        market = market or detect_market(ticker)

        cached = self._cache_get_bars(ticker, period, interval)
        if cached is not None:
            return cached

        df: pd.DataFrame | None = None
        if market == "cn" and self._akshare_enabled:
            df = self._akshare.get_stock_history(ticker)
        elif self._yf_enabled:
            df = self._yfinance.get_stock_history(
                ticker, period=period, interval=interval,
            )
        if df is not None and len(df) > 0:
            self._cache_set_bars(ticker, period, interval, df)
            return df
        logger.warning("History fetch returned empty for %s %s %s",
                       ticker, period, interval)
        return df

    # ── Cache helpers ────────────────────────────────────────────────────

    def _cache_get(self, category: str, key: str) -> Any | None:
        if not (self._enable_cache and self._cache):
            return None
        return self._cache.get(category, key)

    def _cache_set(self, category: str, key: str, value: Any) -> None:
        if self._enable_cache and self._cache:
            self._cache.set(category, key, value)

    def _cache_get_bars(self, ticker: str, period: str, interval: str):
        if not (self._enable_cache and self._cache):
            return None
        return self._cache.get_bars(ticker, period, interval)

    def _cache_set_bars(self, ticker: str, period: str, interval: str, df) -> None:
        if self._enable_cache and self._cache:
            self._cache.set_bars(ticker, period, interval, df)

    # ── Accessors ────────────────────────────────────────────────────────

    @property
    def cache(self) -> LocalCache | None:
        return self._cache

    @property
    def qwen(self) -> QwenProvider:
        return self._qwen

    def routing_summary(self) -> dict:
        return {
            "primary": self._primary,
            "cache_enabled": self._enable_cache,
            "qwen_enabled": self._qwen.enabled,
            "yfinance_enabled": self._yf_enabled,
            "akshare_enabled": self._akshare_enabled,
        }
