"""Data models for portfolio management."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class Position:
    """A stock position in the portfolio."""
    ticker: str
    market: str  # "us" or "cn"
    shares: float
    avg_cost: float
    added_date: str  # YYYY-MM-DD
    user_id: int | None = None  # multi-tenant


@dataclass
class Transaction:
    """A buy/sell transaction record."""
    id: int | None
    ticker: str
    action: str  # "buy" or "sell"
    shares: float
    price: float
    timestamp: str  # YYYY-MM-DD HH:MM:SS
    notes: str = ""
    user_id: int | None = None  # multi-tenant


@dataclass
class DailySnapshot:
    """Daily portfolio snapshot for tracking performance."""
    date: str  # YYYY-MM-DD
    total_value: float
    total_cost: float
    pnl: float
    pnl_pct: float
    positions_json: str  # JSON string of all positions
    user_id: int | None = None  # multi-tenant
