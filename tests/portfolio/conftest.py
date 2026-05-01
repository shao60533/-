"""Stub DataManager so portfolio tests never hit live providers.

PortfolioManager pulls live prices through DataManager during get_holdings
(used by take_snapshot). The fresh-db tests assert the *DB plumbing* —
they shouldn't depend on yfinance/Schwab being reachable. We swap in a
no-op DataManager via autouse fixture before every test in this folder.
"""

from __future__ import annotations

import pytest


class _NullDataManager:
    """Pretends every quote lookup missed — caller falls back to price=0."""

    def __init__(self, *_, **__):
        pass

    def get_price(self, ticker, market=None):
        return None

    def get_prices_batch(self, tickers, market=None):
        return {}


@pytest.fixture(autouse=True)
def _stub_data_manager(monkeypatch):
    monkeypatch.setattr(
        "stock_trading_system.portfolio.manager.DataManager",
        _NullDataManager,
    )
    monkeypatch.setattr(
        "stock_trading_system.alerts.monitor.DataManager",
        _NullDataManager,
    )
    yield
