"""Screener V2 — Agent-driven screening with master philosophies.

Entry point: `ScreenerV2(config, local_cache).run(params, progress_cb)`
"""

from stock_trading_system.screener.v2.orchestrator import ScreenerV2
from stock_trading_system.screener.v2.regime_detector import RegimeDetector, RegimeResult
from stock_trading_system.screener.v2.aggregator import Aggregator
from stock_trading_system.screener.v2.gurus import all_guru_metadata

__all__ = ["ScreenerV2", "RegimeDetector", "RegimeResult", "Aggregator", "all_guru_metadata"]
