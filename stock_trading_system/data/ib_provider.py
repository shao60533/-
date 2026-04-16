"""IB TWS data provider - primary US market data source.

Connects to TWS Desktop via ib_insync. Provides real-time quotes,
historical data, fundamentals, and market scanning.
"""

import asyncio
import time
from datetime import datetime, timedelta

import pandas as pd

from stock_trading_system.utils import get_logger

logger = get_logger("data.ib")


def _make_patched_ib():
    """Return an IB subclass that tolerates reqExecutionsAsync timeouts.

    ib_insync 0.9.x sometimes hangs indefinitely on reqExecutionsAsync when
    the broker sends no execDetailsEnd message.  This subclass catches that
    timeout gracefully so the rest of the connection sequence can proceed.
    """
    from ib_insync import IB

    class _PatchedIB(IB):
        async def connectAsync(
            self,
            host="127.0.0.1",
            port=7497,
            clientId=1,
            timeout=4,
            readonly=False,
            account="",
        ):
            clientId = int(clientId)
            self.wrapper.clientId = clientId
            timeout = timeout or None
            try:
                await self.client.connectAsync(host, port, clientId, timeout)
                if clientId == 0:
                    self.reqAutoOpenOrders(True)
                accounts = self.client.getAccounts()
                if not account and len(accounts) == 1:
                    account = accounts[0]
                reqs = {}
                reqs["positions"] = self.reqPositionsAsync()
                if not readonly:
                    reqs["open orders"] = self.reqOpenOrdersAsync()
                if not readonly and self.client.serverVersion() >= 150:
                    reqs["completed orders"] = self.reqCompletedOrdersAsync(False)
                if account:
                    reqs["account updates"] = self.reqAccountUpdatesAsync(account)
                if len(accounts) <= self.MaxSyncedSubAccounts:
                    for acc in accounts:
                        reqs[f"account updates for {acc}"] = (
                            self.reqAccountUpdatesMultiAsync(acc)
                        )
                tasks = [asyncio.wait_for(req, timeout) for req in reqs.values()]
                resps = await asyncio.gather(*tasks, return_exceptions=True)
                for name, resp in zip(reqs, resps):
                    if isinstance(resp, (asyncio.TimeoutError, TimeoutError)):
                        logger.warning("%s request timed out", name)
                # reqExecutionsAsync can hang if TWS never sends execDetailsEnd;
                # treat a timeout here as non-fatal.
                try:
                    await asyncio.wait_for(self.reqExecutionsAsync(), 5)
                except Exception:
                    logger.warning("reqExecutionsAsync timed out — continuing anyway")
                if not self.client.isReady():
                    raise ConnectionError("Socket connection broken while connecting")
                self._logger.info("Synchronization complete")
                self.connectedEvent.emit()
            except BaseException:
                self.disconnect()
                raise
            return self

    return _PatchedIB()


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
            self._ib = _make_patched_ib()
            # Use ib_insync's own sync connect() path so the event loop stays
            # consistent with subsequent sync calls (qualifyContracts, etc.)
            self._ib.connect(
                host=self._config.get("host", "127.0.0.1"),
                port=self._config.get("port", 7496),
                clientId=self._config.get("client_id", 1),
                timeout=15,
            )
            self._connected = True
            logger.info(
                "Connected to IB TWS at %s:%s",
                self._config.get("host"),
                self._config.get("port"),
            )
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
        """Get price for a US stock.

        Tries real-time market data first; if unavailable (no subscription),
        falls back to the most recent historical close.
        """
        try:
            self._ensure_connected()
            contract = self._make_stock_contract(ticker)
            self._ib.qualifyContracts(contract)

            # Try real-time data
            ticker_data = self._ib.reqMktData(contract, "", False, False)
            self._ib.sleep(2)

            last = ticker_data.last if ticker_data.last == ticker_data.last else None
            close = ticker_data.close if ticker_data.close == ticker_data.close else None
            self._ib.cancelMktData(contract)

            if last or close:
                return {
                    "ticker": ticker,
                    "last": last,
                    "close": close,
                    "bid": ticker_data.bid if ticker_data.bid == ticker_data.bid else None,
                    "ask": ticker_data.ask if ticker_data.ask == ticker_data.ask else None,
                    "high": ticker_data.high if ticker_data.high == ticker_data.high else None,
                    "low": ticker_data.low if ticker_data.low == ticker_data.low else None,
                    "volume": ticker_data.volume if ticker_data.volume == ticker_data.volume else None,
                }

            # No real-time data (no subscription) — use last historical close
            logger.info("IB no realtime for %s, using historical close", ticker)
            bars = self._ib.reqHistoricalData(
                contract, endDateTime="", durationStr="2 D",
                barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
            )
            if bars:
                b = bars[-1]
                return {
                    "ticker": ticker,
                    "last": b.close,
                    "close": b.close,
                    "high": b.high,
                    "low": b.low,
                    "volume": int(b.volume),
                }

            return None
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
