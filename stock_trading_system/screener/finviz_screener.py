"""Layer 2: Finviz fundamental screening - US stocks.

Uses finvizfinance to get 90+ fundamental metrics and filter candidates.
"""

from stock_trading_system.screener.criteria import ScreenCriteria
from stock_trading_system.utils import get_logger

logger = get_logger("screener.finviz")


class FinvizScreener:
    """Finviz-based fundamental stock screener for US market."""

    def filter(self, tickers: list[str], criteria: ScreenCriteria) -> list[dict]:
        """Filter tickers using Finviz fundamental data.

        Args:
            tickers: List of candidate ticker symbols
            criteria: Screening criteria to apply

        Returns:
            List of dicts with ticker info and fundamental data, sorted by relevance
        """
        if not tickers:
            return []

        results = []
        for ticker in tickers:
            info = self._get_stock_info(ticker)
            if info and self._passes_criteria(info, criteria):
                results.append(info)

        # Sort by market cap descending
        results.sort(key=lambda x: x.get("market_cap_val", 0), reverse=True)
        logger.info("Finviz filter: %d/%d passed criteria", len(results), len(tickers))
        return results[:criteria.top_n * 3]  # Keep 3x top_n for AI screening

    def _get_stock_info(self, ticker: str) -> dict | None:
        """Get fundamental data for a single stock from Finviz."""
        try:
            from finvizfinance.quote import finvizfinance

            stock = finvizfinance(ticker)
            data = stock.ticker_fundament()

            return {
                "ticker": ticker,
                "name": data.get("Company", ""),
                "sector": data.get("Sector", ""),
                "industry": data.get("Industry", ""),
                "price": data.get("Price", ""),
                "pe": _parse_float(data.get("P/E", "")),
                "pb": _parse_float(data.get("P/B", "")),
                "roe": _parse_percent(data.get("ROE", "")),
                "eps_growth": _parse_percent(data.get("EPS next Y", "")),
                "revenue_growth": _parse_percent(data.get("Sales past 5Y", "")),
                "market_cap": data.get("Market Cap", ""),
                "market_cap_val": _parse_market_cap(data.get("Market Cap", "")),
                "volume": data.get("Volume", ""),
                "rsi": _parse_float(data.get("RSI (14)", "")),
                "target_price": data.get("Target Price", ""),
                "analyst_recom": data.get("Recom", ""),
            }
        except Exception as e:
            logger.debug("Finviz data unavailable for %s: %s", ticker, e)
            return None

    def _passes_criteria(self, info: dict, criteria: ScreenCriteria) -> bool:
        """Check if stock info passes screening criteria."""
        pe = info.get("pe")
        if pe is not None:
            if criteria.min_pe and pe < criteria.min_pe:
                return False
            if criteria.max_pe and pe > criteria.max_pe:
                return False

        pb = info.get("pb")
        if pb is not None and criteria.max_pb and pb > criteria.max_pb:
            return False

        roe = info.get("roe")
        if roe is not None and criteria.min_roe and roe < criteria.min_roe:
            return False

        rev_growth = info.get("revenue_growth")
        if rev_growth is not None and criteria.min_revenue_growth and rev_growth < criteria.min_revenue_growth:
            return False

        market_cap = info.get("market_cap_val", 0)
        if criteria.min_market_cap and market_cap < criteria.min_market_cap:
            return False
        if criteria.max_market_cap and market_cap > criteria.max_market_cap:
            return False

        return True


def _parse_float(value: str) -> float | None:
    """Parse a float from string, return None if invalid."""
    if not value or value == "-":
        return None
    try:
        return float(value.replace(",", "").replace("%", ""))
    except (ValueError, AttributeError):
        return None


def _parse_percent(value: str) -> float | None:
    """Parse a percentage string like '15.30%' to 0.153."""
    if not value or value == "-":
        return None
    try:
        return float(value.replace("%", "").replace(",", "")) / 100
    except (ValueError, AttributeError):
        return None


def _parse_market_cap(value: str) -> float:
    """Parse market cap string like '2.5T', '150B', '800M' to float."""
    if not value or value == "-":
        return 0
    try:
        value = value.strip()
        multiplier = 1
        if value.endswith("T"):
            multiplier = 1e12
            value = value[:-1]
        elif value.endswith("B"):
            multiplier = 1e9
            value = value[:-1]
        elif value.endswith("M"):
            multiplier = 1e6
            value = value[:-1]
        elif value.endswith("K"):
            multiplier = 1e3
            value = value[:-1]
        return float(value.replace(",", "")) * multiplier
    except (ValueError, AttributeError):
        return 0
