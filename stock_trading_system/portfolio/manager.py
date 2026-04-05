"""Portfolio manager - manual entry of positions with real-time P&L calculation."""

import json
from datetime import datetime
from pathlib import Path

from stock_trading_system.portfolio.database import PortfolioDatabase
from stock_trading_system.portfolio.models import Position, Transaction, DailySnapshot
from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import detect_market

logger = get_logger("portfolio.manager")


class PortfolioManager:
    """Portfolio manager with manual position entry and real-time P&L."""

    def __init__(self, config: dict):
        self._config = config
        db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
        self._db = PortfolioDatabase(db_path)
        self._data_manager = DataManager(config)

    # ── Manual Entry ─────────────────────────────────────────────────────

    def add_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        market: str | None = None,
        date: str | None = None,
        notes: str = "",
    ):
        """Record a buy and update position.

        If position exists, calculates new average cost.
        """
        market = market or detect_market(ticker)
        date = date or datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Record transaction
        txn = Transaction(
            id=None, ticker=ticker, action="buy",
            shares=shares, price=price, timestamp=timestamp, notes=notes,
        )
        self._db.add_transaction(txn)

        # Update position
        existing = self._db.get_position(ticker)
        if existing:
            total_cost = existing.shares * existing.avg_cost + shares * price
            new_shares = existing.shares + shares
            new_avg = total_cost / new_shares
            existing.shares = new_shares
            existing.avg_cost = new_avg
            self._db.upsert_position(existing)
        else:
            pos = Position(
                ticker=ticker, market=market,
                shares=shares, avg_cost=price, added_date=date,
            )
            self._db.upsert_position(pos)

        logger.info("Added: BUY %s %s @ %s", shares, ticker, price)

    def sell_position(
        self,
        ticker: str,
        shares: float,
        price: float,
        date: str | None = None,
        notes: str = "",
    ):
        """Record a sell and update position.

        Removes position if all shares sold.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        txn = Transaction(
            id=None, ticker=ticker, action="sell",
            shares=shares, price=price, timestamp=timestamp, notes=notes,
        )
        self._db.add_transaction(txn)

        existing = self._db.get_position(ticker)
        if existing:
            remaining = existing.shares - shares
            if remaining <= 0:
                self._db.delete_position(ticker)
                logger.info("Sold all: %s %s @ %s (position closed)", shares, ticker, price)
            else:
                existing.shares = remaining
                self._db.upsert_position(existing)
                logger.info("Sold: %s %s @ %s (remaining: %s)", shares, ticker, price, remaining)
        else:
            logger.warning("No position found for %s, recording transaction only", ticker)

    def update_cost(self, ticker: str, avg_cost: float):
        """Manually correct the average cost for a position."""
        existing = self._db.get_position(ticker)
        if existing:
            existing.avg_cost = avg_cost
            self._db.upsert_position(existing)
            logger.info("Updated avg cost for %s to %s", ticker, avg_cost)

    # ── Queries ──────────────────────────────────────────────────────────

    def get_holdings(self) -> list[dict]:
        """Get all positions with real-time price and P&L."""
        positions = self._db.get_all_positions()
        holdings = []

        for pos in positions:
            price_data = self._data_manager.get_price(pos.ticker, market=pos.market)
            current_price = 0
            if price_data:
                current_price = price_data.get("last") or price_data.get("close") or 0

            pnl = (current_price - pos.avg_cost) * pos.shares
            pnl_pct = ((current_price / pos.avg_cost) - 1) * 100 if pos.avg_cost > 0 else 0

            holdings.append({
                "ticker": pos.ticker,
                "market": pos.market,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": current_price,
                "market_value": current_price * pos.shares,
                "cost_basis": pos.avg_cost * pos.shares,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "added_date": pos.added_date,
            })

        return holdings

    def get_transactions(self, ticker: str | None = None) -> list[dict]:
        """Get transaction history."""
        txns = self._db.get_transactions(ticker)
        return [
            {
                "id": t.id,
                "ticker": t.ticker,
                "action": t.action,
                "shares": t.shares,
                "price": t.price,
                "date": t.timestamp,
                "notes": t.notes,
            }
            for t in txns
        ]

    def get_pnl(self) -> dict:
        """Get portfolio-level P&L summary."""
        holdings = self.get_holdings()

        total_cost = sum(h["cost_basis"] for h in holdings)
        total_value = sum(h["market_value"] for h in holdings)
        total_pnl = total_value - total_cost
        total_pnl_pct = ((total_value / total_cost) - 1) * 100 if total_cost > 0 else 0

        return {
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "positions": len(holdings),
        }

    def get_allocation(self) -> list[dict]:
        """Get position allocation breakdown."""
        holdings = self.get_holdings()
        total_value = sum(h["market_value"] for h in holdings)

        if total_value == 0:
            return []

        return [
            {
                "ticker": h["ticker"],
                "market": h["market"],
                "value": h["market_value"],
                "weight": h["market_value"] / total_value,
            }
            for h in sorted(holdings, key=lambda x: x["market_value"], reverse=True)
        ]

    # ── Snapshots ────────────────────────────────────────────────────────

    def take_snapshot(self):
        """Save a daily portfolio snapshot."""
        holdings = self.get_holdings()
        pnl = self.get_pnl()

        snapshot = DailySnapshot(
            date=datetime.now().strftime("%Y-%m-%d"),
            total_value=pnl["total_value"],
            total_cost=pnl["total_cost"],
            pnl=pnl["total_pnl"],
            pnl_pct=pnl["total_pnl_pct"],
            positions_json=json.dumps(holdings, default=str),
        )
        self._db.save_snapshot(snapshot)
        logger.info("Snapshot saved for %s", snapshot.date)

    def get_history(self, days: int = 30) -> list[dict]:
        """Get historical portfolio snapshots."""
        snapshots = self._db.get_snapshots(days)
        return [
            {
                "date": s.date,
                "total_value": s.total_value,
                "total_cost": s.total_cost,
                "pnl": s.pnl,
                "pnl_pct": s.pnl_pct,
            }
            for s in snapshots
        ]
