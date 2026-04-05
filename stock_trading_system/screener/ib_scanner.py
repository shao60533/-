"""Layer 1: IB Market Scanner - coarse stock screening using IB TWS.

Uses IB's built-in market scanner to get initial candidate list (50-100 stocks).
"""

from stock_trading_system.data.ib_provider import IBProvider
from stock_trading_system.screener.criteria import ScreenCriteria, IB_SCAN_TYPES
from stock_trading_system.utils import get_logger

logger = get_logger("screener.ib")


class IBScanner:
    """IB TWS Market Scanner for initial stock screening."""

    def __init__(self, ib_provider: IBProvider):
        self._ib = ib_provider

    def scan(
        self,
        strategy: str = "growth",
        criteria: ScreenCriteria | None = None,
        max_results: int = 50,
    ) -> list[str]:
        """Run IB market scanner and return candidate ticker list.

        Args:
            strategy: Strategy name ("growth", "value", "momentum", "low_volatility")
            criteria: Optional screening criteria for additional filters
            max_results: Maximum number of results

        Returns:
            List of ticker symbols
        """
        scan_type = IB_SCAN_TYPES.get(strategy, "MOST_ACTIVE")

        params = {"max_results": max_results}
        if criteria:
            if criteria.min_price:
                params["above_price"] = criteria.min_price
            if criteria.max_price:
                params["below_price"] = criteria.max_price
            if criteria.min_volume:
                params["above_volume"] = criteria.min_volume
            if criteria.min_market_cap:
                params["market_cap_above"] = criteria.min_market_cap

        logger.info("Running IB scanner: type=%s, params=%s", scan_type, params)
        tickers = self._ib.scan_market(scan_type, **params)
        logger.info("IB scanner returned %d candidates", len(tickers))
        return tickers
