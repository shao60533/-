"""A-share stock screener using AkShare data."""

from stock_trading_system.data.akshare_provider import AkShareProvider
from stock_trading_system.screener.criteria import ScreenCriteria, CN_COLUMN_MAP
from stock_trading_system.utils import get_logger

logger = get_logger("screener.akshare")


class AkShareScreener:
    """A-share stock screener using AkShare real-time data."""

    def __init__(self):
        self._provider = AkShareProvider()

    def screen(self, criteria: ScreenCriteria) -> list[dict]:
        """Screen all A-share stocks by criteria.

        Returns:
            List of stock dicts passing the criteria, sorted by market cap
        """
        df = self._provider.get_all_stocks()
        if df is None or df.empty:
            logger.error("Failed to get A-share stock list")
            return []

        col = CN_COLUMN_MAP
        original_count = len(df)

        # Filter by price
        if criteria.min_price:
            df = df[df[col["price"]].astype(float, errors="ignore") >= criteria.min_price]

        # Filter by volume
        if criteria.min_volume:
            df = df[df[col["volume"]].astype(float, errors="ignore") >= criteria.min_volume]

        # Filter by market cap
        if criteria.min_market_cap:
            df = df[df[col["market_cap"]].astype(float, errors="ignore") >= criteria.min_market_cap]

        # Filter by PE
        pe_col = col["pe"]
        if pe_col in df.columns:
            # Remove stocks with no PE or negative PE
            df = df[df[pe_col].astype(float, errors="ignore") > 0]
            if criteria.max_pe:
                df = df[df[pe_col].astype(float, errors="ignore") <= criteria.max_pe]
            if criteria.min_pe:
                df = df[df[pe_col].astype(float, errors="ignore") >= criteria.min_pe]

        # Sort by market cap descending
        df = df.sort_values(col["market_cap"], ascending=False)

        # Take top N * 3 (leave room for AI screening)
        df = df.head(criteria.top_n * 3)

        results = []
        for _, row in df.iterrows():
            results.append({
                "ticker": str(row[col["code"]]),
                "name": str(row[col["name"]]),
                "price": str(row.get(col["price"], "")),
                "change_pct": str(row.get(col["change_pct"], "")),
                "volume": str(row.get(col["volume"], "")),
                "market_cap": str(row.get(col["market_cap"], "")),
                "pe": str(row.get(col["pe"], "")),
                "turnover": str(row.get(col["turnover"], "")),
            })

        logger.info("A-share screener: %d/%d passed criteria", len(results), original_count)
        return results
