"""Paper-trade module — observe AI analysis effectiveness via simulated trading."""

from stock_trading_system.strategy.paper_trader.session_store import PaperTradeStore
from stock_trading_system.strategy.paper_trader.signal_loader import SignalLoader
from stock_trading_system.strategy.paper_trader.simulator import PaperTradeSimulator
from stock_trading_system.strategy.paper_trader.metrics import (
    compute_session_metrics, ticker_breakdown,
)
from stock_trading_system.strategy.paper_trader.tracking import (
    auto_track_analysis, manual_track, ticker_summary,
)
from stock_trading_system.strategy.paper_trader.ticker_session_manager import (
    ensure_ticker_session,
)
from stock_trading_system.strategy.paper_trader.action_decider import decide_action
from stock_trading_system.strategy.paper_trader.event_executor import process_analysis
from stock_trading_system.strategy.paper_trader.daily_updater import DailyUpdater
from stock_trading_system.strategy.paper_trader.backfill import backfill_all
from stock_trading_system.strategy.paper_trader.plan_parser import extract_plan
from stock_trading_system.strategy.paper_trader import order_engine
from stock_trading_system.strategy.paper_trader.eod_runner import (
    EodRunSummary, EodSessionResult,
    run_paper_trade_eod_all, run_paper_trade_eod_for_ticker,
    paper_trade_status_snapshot, get_last_run,
)

__all__ = [
    "PaperTradeStore", "SignalLoader", "PaperTradeSimulator",
    "compute_session_metrics", "ticker_breakdown",
    "auto_track_analysis", "manual_track", "ticker_summary",
    "ensure_ticker_session", "decide_action", "process_analysis",
    "DailyUpdater", "backfill_all",
    "extract_plan", "order_engine",
    # v1.x paper-trade EOD auto-update wiring
    "EodRunSummary", "EodSessionResult",
    "run_paper_trade_eod_all", "run_paper_trade_eod_for_ticker",
    "paper_trade_status_snapshot", "get_last_run",
]
