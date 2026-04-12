"""AkShare data provider - A-share (Chinese market) data source.

Free, no API key required. Covers all A-share stocks.
"""

import pandas as pd

from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import normalize_cn_ticker

logger = get_logger("data.akshare")


class AkShareProvider:
    """AkShare data provider for Chinese A-share market."""

    def get_stock_price(self, ticker: str) -> dict | None:
        """Get real-time price for an A-share stock."""
        try:
            import akshare as ak

            code = normalize_cn_ticker(ticker)
            df = ak.stock_zh_a_spot_em()

            row = df[df["代码"] == code]
            if row.empty:
                return None

            row = row.iloc[0]
            return {
                "ticker": code,
                "name": row.get("名称", ""),
                "last": float(row.get("最新价", 0)),
                "open": float(row.get("今开", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "close": float(row.get("最新价", 0)),
                "volume": float(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "turnover": float(row.get("换手率", 0)),
                "pe": float(row.get("市盈率-动态", 0)) if row.get("市盈率-动态") else None,
                "market_cap": float(row.get("总市值", 0)),
            }
        except Exception as e:
            logger.error("AkShare get_stock_price(%s) failed: %s", ticker, e)
            return None

    def get_stock_history(
        self,
        ticker: str,
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "qfq",
    ) -> pd.DataFrame | None:
        """Get historical OHLCV data for an A-share stock.

        Args:
            ticker: 6-digit stock code
            period: "daily", "weekly", "monthly"
            start_date: YYYYMMDD
            end_date: YYYYMMDD
            adjust: "qfq" (forward), "hfq" (backward), "" (no adjust)
        """
        try:
            import akshare as ak

            code = normalize_cn_ticker(ticker)
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

            if df is None or df.empty:
                return None

            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "涨跌幅": "change_pct",
                "换手率": "turnover",
            })
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            return df
        except Exception as e:
            logger.error("AkShare get_stock_history(%s) failed: %s", ticker, e)
            return None

    def get_fundamentals(self, ticker: str) -> dict | None:
        """Get basic fundamental info for an A-share stock."""
        try:
            import akshare as ak

            code = normalize_cn_ticker(ticker)
            df = ak.stock_individual_info_em(symbol=code)

            if df is None or df.empty:
                return None

            info = {}
            for _, row in df.iterrows():
                info[row["item"]] = row["value"]
            return info
        except Exception as e:
            logger.error("AkShare get_fundamentals(%s) failed: %s", ticker, e)
            return None

    def get_news(self, ticker: str) -> list[dict]:
        """Get recent news for an A-share stock."""
        try:
            import akshare as ak

            code = normalize_cn_ticker(ticker)
            df = ak.stock_news_em(symbol=code)

            if df is None or df.empty:
                return []

            news = []
            for _, row in df.head(20).iterrows():
                news.append({
                    "title": row.get("新闻标题", ""),
                    "url": row.get("新闻链接", ""),
                    "published": str(row.get("发布时间", "")),
                    "source": row.get("文章来源", ""),
                })
            return news
        except Exception as e:
            logger.error("AkShare get_news(%s) failed: %s", ticker, e)
            return []

    def get_all_stocks(self) -> pd.DataFrame | None:
        """Get real-time snapshot of all A-share stocks (for screening)."""
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            return df
        except Exception as e:
            logger.error("AkShare get_all_stocks failed: %s", e)
            return None
