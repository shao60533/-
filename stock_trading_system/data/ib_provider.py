"""IB TWS data provider - primary US market data source.

Connects to TWS Desktop via ib_insync. Provides real-time quotes,
historical data, fundamentals, and market scanning.
"""

import time
from datetime import datetime, timedelta

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.ib")


class IBProvider:
    """Interactive Brokers TWS data provider."""

    def __init__(self, config: dict):
        self._config = config.get("ib", {})
        self._ib = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to TWS. Returns True if successful."""
        if self._connected and self._ib and self._ib.isConnected():
            return True

        try:
            from ib_insync import IB

            self._ib = IB()
            self._ib.connect(
                host=self._config.get("host", "127.0.0.1"),
                port=self._config.get("port", 7496),
                clientId=self._config.get("client_id", 1),
            )
            self._connected = True
            logger.info("Connected to IB TWS at %s:%s", self._config.get("host"), self._config.get("port"))
            return True
        except Exception as e:
            logger.warning("Failed to connect to IB TWS: %s", e)
            self._connected = False
            return False

    def disconnect(self):
        """Disconnect from TWS."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IB TWS")

    def is_connected(self) -> bool:
        return self._connected and self._ib and self._ib.isConnected()

    def _ensure_connected(self):
        if not self.is_connected():
            if not self.connect():
                raise ConnectionError("Cannot connect to IB TWS")

    def _make_stock_contract(self, ticker: str):
        from ib_insync import Stock

        return Stock(ticker, "SMART", "USD")

    def get_stock_price(self, ticker: str) -> dict | None:
        """Get real-time price snapshot for a US stock."""
        try:
            self._ensure_connected()
            contract = self._make_stock_contract(ticker)
            self._ib.qualifyContracts(contract)
            ticker_data = self._ib.reqMktData(contract, "", False, False)
            # Wait briefly for data
            self._ib.sleep(2)

            result = {
                "ticker": ticker,
                "last": ticker_data.last if ticker_data.last == ticker_data.last else None,
                "bid": ticker_data.bid if ticker_data.bid == ticker_data.bid else None,
                "ask": ticker_data.ask if ticker_data.ask == ticker_data.ask else None,
                "high": ticker_data.high if ticker_data.high == ticker_data.high else None,
                "low": ticker_data.low if ticker_data.low == ticker_data.low else None,
                "close": ticker_data.close if ticker_data.close == ticker_data.close else None,
                "volume": ticker_data.volume if ticker_data.volume == ticker_data.volume else None,
            }

            self._ib.cancelMktData(contract)
            return result
        except Exception as e:
            logger.error("IB get_stock_price(%s) failed: %s", ticker, e)
            return None

    def get_stock_history(
        self,
        ticker: str,
        duration: str = "1 Y",
        bar_size: str = "1 day",
        what_to_show: str = "TRADES",
    ) -> pd.DataFrame | None:
        """Get historical OHLCV data.

        Args:
            ticker: Stock symbol
            duration: e.g. "1 Y", "6 M", "30 D"
            bar_size: e.g. "1 day", "1 hour", "5 mins"
            what_to_show: "TRADES", "MIDPOINT", "BID", "ASK"
        """
        try:
            self._ensure_connected()
            contract = self._make_stock_contract(ticker)
            self._ib.qualifyContracts(contract)

            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                return None

            df = pd.DataFrame([{
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            } for b in bars])

            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            return df
        except Exception as e:
            logger.error("IB get_stock_history(%s) failed: %s", ticker, e)
            return None

    def get_fundamentals(self, ticker: str) -> str | None:
        """Get fundamental data XML from IB."""
        try:
            self._ensure_connected()
            contract = self._make_stock_contract(ticker)
            self._ib.qualifyContracts(contract)
            data = self._ib.reqFundamentalData(contract, "ReportSnapshot")
            return data
        except Exception as e:
            logger.error("IB get_fundamentals(%s) failed: %s", ticker, e)
            return None

    def subscribe_realtime(self, ticker: str, callback):
        """Subscribe to real-time market data updates.

        Args:
            ticker: Stock symbol
            callback: Function called with ticker data on each update
        """
        self._ensure_connected()
        contract = self._make_stock_contract(ticker)
        self._ib.qualifyContracts(contract)
        ticker_data = self._ib.reqMktData(contract, "", False, False)
        ticker_data.updateEvent += callback
        return ticker_data

    def scan_market(self, scan_type: str, **params) -> list[str]:
        """Run IB market scanner to get candidate tickers.

        Args:
            scan_type: Scanner type, e.g.:
                - TOP_PERC_GAIN, TOP_PERC_LOSE
                - MOST_ACTIVE, HOT_BY_VOLUME
                - HIGH_VS_13W_HL, HIGH_VS_52W_HL
                - TOP_TRADE_RATE
        """
        try:
            self._ensure_connected()
            from ib_insync import ScannerSubscription

            sub = ScannerSubscription(
                instrument="STK",
                locationCode="STK.US.MAJOR",
                scanCode=scan_type,
                numberOfRows=params.get("max_results", 50),
            )

            # Apply optional filters
            if "above_price" in params:
                sub.abovePrice = params["above_price"]
            if "below_price" in params:
                sub.belowPrice = params["below_price"]
            if "above_volume" in params:
                sub.aboveVolume = params["above_volume"]
            if "market_cap_above" in params:
                sub.marketCapAbove = params["market_cap_above"]

            results = self._ib.reqScannerData(sub, [])

            tickers = []
            for item in results:
                if item.contractDetails and item.contractDetails.contract:
                    tickers.append(item.contractDetails.contract.symbol)

            logger.info("IB scanner %s returned %d results", scan_type, len(tickers))
            return tickers
        except Exception as e:
            logger.error("IB scan_market(%s) failed: %s", scan_type, e)
            return []

    def search_symbols(self, pattern: str) -> list[dict]:
        """Search for matching symbols."""
        try:
            self._ensure_connected()
            results = self._ib.reqMatchingSymbols(pattern)
            return [
                {
                    "symbol": r.contract.symbol,
                    "type": r.contract.secType,
                    "exchange": r.contract.primaryExchange,
                    "currency": r.contract.currency,
                }
                for r in (results or [])
            ]
        except Exception as e:
            logger.error("IB search_symbols(%s) failed: %s", pattern, e)
            return []
