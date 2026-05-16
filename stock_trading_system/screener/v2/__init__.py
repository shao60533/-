"""Screener V2 — Agent-driven screening with master philosophies — DEPRECATED.

hardening-iteration-v1 P3.1 [H12] — V2 is on the retirement path,
superseded by V3 (``stock_trading_system.screener.v3.pipeline``). V3
keeps the agent-driven approach and adds: 14 guru agents (was: 6),
roundtable consensus, EOD-aware cache, async pipeline so fan-out
parallelises cleanly.

Two callers still bind here:

    tasks/workers.py:712   (legacy ``screen_v2`` worker)
    tasks/workers.py:1214  (legacy bookmark sync)

Both flip to V3 once the sync wrapper / worker schema mapping lands.

Entry point: `ScreenerV2(config, local_cache).run(params, progress_cb)`
"""

import warnings

from stock_trading_system.screener.v2.orchestrator import ScreenerV2
from stock_trading_system.screener.v2.regime_detector import RegimeDetector, RegimeResult
from stock_trading_system.screener.v2.aggregator import Aggregator
from stock_trading_system.screener.v2.gurus import all_guru_metadata

warnings.warn(
    "stock_trading_system.screener.v2 is deprecated — use "
    "stock_trading_system.screener.v3 (14 guru agents + roundtable + "
    "EOD-aware cache + async pipeline). Scheduled for deletion after "
    "the v3 sync-wrapper PR retires the remaining worker call sites. "
    "See hardening-iteration-v1 P3.1 / H12.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ScreenerV2", "RegimeDetector", "RegimeResult", "Aggregator", "all_guru_metadata"]
