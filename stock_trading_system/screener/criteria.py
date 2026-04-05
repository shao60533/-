"""Stock screening criteria and strategy templates."""

from dataclasses import dataclass, field


@dataclass
class ScreenCriteria:
    """Screening criteria for stock filtering."""
    min_market_cap: float = 1e9
    max_market_cap: float | None = None
    min_volume: int = 500_000
    max_pe: float = 50
    min_pe: float = 0
    max_pb: float | None = None
    min_roe: float | None = None
    min_revenue_growth: float | None = None
    min_price: float = 5.0
    max_price: float | None = None
    top_n: int = 10


# Pre-built strategy templates

STRATEGIES = {
    "growth": ScreenCriteria(
        min_market_cap=5e9,
        min_volume=1_000_000,
        max_pe=60,
        min_pe=5,
        min_revenue_growth=0.15,
        top_n=10,
    ),
    "value": ScreenCriteria(
        min_market_cap=2e9,
        min_volume=500_000,
        max_pe=20,
        min_pe=1,
        max_pb=3.0,
        min_roe=0.10,
        top_n=10,
    ),
    "momentum": ScreenCriteria(
        min_market_cap=1e9,
        min_volume=2_000_000,
        max_pe=80,
        min_price=10.0,
        top_n=10,
    ),
    "low_volatility": ScreenCriteria(
        min_market_cap=10e9,
        min_volume=500_000,
        max_pe=30,
        min_pe=5,
        top_n=10,
    ),
}

# IB Scanner types mapped to strategies
IB_SCAN_TYPES = {
    "growth": "TOP_PERC_GAIN",
    "value": "LOW_PE_ASC",
    "momentum": "HOT_BY_VOLUME",
    "low_volatility": "LOW_STDEV_30D",
}

# A-share screening column mappings
CN_COLUMN_MAP = {
    "code": "代码",
    "name": "名称",
    "price": "最新价",
    "change_pct": "涨跌幅",
    "volume": "成交量",
    "amount": "成交额",
    "market_cap": "总市值",
    "pe": "市盈率-动态",
    "turnover": "换手率",
}
