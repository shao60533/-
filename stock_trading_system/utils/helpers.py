"""Shared utility functions."""

import re
from datetime import datetime
from stock_trading_system.utils.timez import now_local, today_str_ny


def detect_market(ticker: str) -> str:
    """Detect market from ticker format.

    Rules:
        - 6-digit number or ends with .SH/.SZ -> "cn"
        - Otherwise -> "us"
    """
    ticker = ticker.strip().upper()
    # A-share: 6 digits, optionally with .SH or .SZ suffix
    if re.match(r"^\d{6}(\.S[HZ])?$", ticker):
        return "cn"
    return "us"


def normalize_cn_ticker(ticker: str) -> str:
    """Normalize A-share ticker to 6-digit format without suffix."""
    return ticker.strip().split(".")[0]


def format_currency(value: float, market: str = "us") -> str:
    """Format a monetary value with currency symbol."""
    if market == "cn":
        return f"¥{value:,.2f}"
    return f"${value:,.2f}"


def format_percent(value: float) -> str:
    """Format a percentage value."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def format_large_number(value: float) -> str:
    """Format large numbers with B/M/K suffixes."""
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:.0f}"


def today_str() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return today_str_ny()
