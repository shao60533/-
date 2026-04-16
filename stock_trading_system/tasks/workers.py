"""Task workers — bridge between TaskManager and business logic.

Each worker signature: fn(params: dict, progress_cb) -> result_dict.

Workers are registered with TaskManager by `register_workers(tm, getters)`.
`getters` is a small dependency bundle so tests can inject fakes.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from stock_trading_system.utils import get_logger

logger = get_logger("tasks.workers")


# Progress callback signature: (percent, step_desc=None, partial=None) -> None
ProgressCb = Callable[..., None]


# ── Analysis worker ───────────────────────────────────────────────────────────


def make_analysis_worker(get_analyzer, get_strategy_engine, get_portfolio, get_router):
    """Factory that builds an analysis worker bound to the given getters."""

    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        ticker = (params.get("ticker") or "").upper().strip()
        if not ticker:
            raise ValueError("Missing 'ticker' in params")
        date = params.get("date")
        if not date:
            from stock_trading_system.utils.helpers import today_str
            date = today_str()

        progress_cb(5, "初始化分析管线")
        analyzer = get_analyzer()

        # TradingAgents' analyze() is monolithic (no internal progress hook),
        # so we report coarse-grained milestones only.
        progress_cb(15, "启动 7 Agent 分析")
        result = analyzer.analyze(ticker, date)

        progress_cb(85, "生成策略建议")
        advice = _build_advice(result, ticker, get_strategy_engine, get_portfolio,
                               get_router)

        progress_cb(98, "整理结果")
        return {
            "ticker": ticker,
            "date": date,
            "signal": result.signal,
            "market_report": result.market_report,
            "sentiment_report": result.sentiment_report,
            "news_report": result.news_report,
            "fundamentals_report": result.fundamentals_report,
            "investment_debate": str(result.investment_debate),
            "risk_assessment": str(result.risk_assessment),
            "trade_decision": str(result.trade_decision),
            "advice": advice,
        }

    return worker


def _build_advice(result, ticker, get_strategy_engine, get_portfolio, get_router):
    try:
        engine = get_strategy_engine()
        holdings = get_portfolio().get_holdings()
        router = get_router()
        price_data = router.get_price(ticker) if router else None
        current_price = None
        if price_data:
            current_price = price_data.get("last") or price_data.get("close")
        advice_obj = engine.generate_advice(result, holdings, current_price)
        return {
            "action": advice_obj.action,
            "confidence": advice_obj.confidence,
            "suggested_position_pct": advice_obj.suggested_position_pct,
            "entry_price_low": advice_obj.entry_price_low,
            "entry_price_high": advice_obj.entry_price_high,
            "stop_loss": advice_obj.stop_loss,
            "take_profit": advice_obj.take_profit,
            "reasoning": advice_obj.reasoning,
            "risk_warning": advice_obj.risk_warning,
        }
    except Exception as e:  # noqa: BLE001 — advice is best-effort
        logger.warning("Strategy advice failed for %s: %s", ticker, e)
        return None


# ── Screen worker ─────────────────────────────────────────────────────────────


def make_screen_worker(get_screener):
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        market = params.get("market", "us")
        strategy = params.get("strategy", "growth")
        progress_cb(10, f"IB Scanner ({market})")
        screener = get_screener()
        # The underlying screener does 3 layers; we report at the end only
        # because screener.screen() is also monolithic. This is enough for
        # the task center to show "running" → "success".
        progress_cb(40, f"finviz 基本面筛选")
        results = screener.screen(market=market, strategy=strategy) or []
        progress_cb(90, f"AI 精选 ({len(results)} 只)")
        return {
            "market": market,
            "strategy": strategy,
            "results": results,
            "count": len(results),
        }
    return worker


# ── Report worker ─────────────────────────────────────────────────────────────


def make_report_worker(get_report_gen):
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        rtype = params.get("type", "daily")
        ticker = params.get("ticker")
        progress_cb(20, f"生成 {rtype} 报告")
        gen = get_report_gen()
        if rtype == "daily":
            content = gen.daily_report()
        elif rtype == "weekly":
            content = gen.weekly_report()
        elif rtype == "monthly":
            content = gen.monthly_report()
        elif rtype == "stock":
            if not ticker:
                raise ValueError("stock report requires a ticker")
            content = gen.stock_report(ticker.upper())
        else:
            raise ValueError(f"Unknown report type: {rtype}")
        progress_cb(95, "完成")
        return {"type": rtype, "ticker": (ticker or "").upper(),
                "content": content}
    return worker


# ── Qwen quick workers (for users who want async even for data fetches) ──────


def make_qwen_fundamentals_worker(get_router):
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        ticker = (params.get("ticker") or "").upper().strip()
        if not ticker:
            raise ValueError("Missing 'ticker'")
        progress_cb(30, "查询基本面")
        data = get_router().get_fundamentals(ticker)
        if not data:
            raise ValueError(f"No fundamentals returned for {ticker}")
        progress_cb(95, "完成")
        return {"ticker": ticker, "fundamentals": data}
    return worker


def make_qwen_news_worker(get_router):
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        ticker = (params.get("ticker") or "").upper().strip()
        if not ticker:
            raise ValueError("Missing 'ticker'")
        limit = int(params.get("limit", 10))
        progress_cb(30, "查询新闻")
        items = get_router().get_news(ticker, limit=limit)
        progress_cb(95, "完成")
        return {"ticker": ticker, "news": items, "count": len(items)}
    return worker


# ── V2 Screener worker stub (full impl lives in screener.v2) ─────────────────


def make_screen_v2_worker():
    """Stub for the agent + guru-driven Screener V2.

    The real worker is registered by the screener.v2 package once
    orchestrator.run_v2 lands. Until then this stub surfaces a clear
    error instead of crashing the registry on import.
    """
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        try:
            from stock_trading_system.screener.v2.orchestrator import run_v2
        except ImportError as e:
            raise NotImplementedError(
                "Screener V2 not yet wired (screener.v2.orchestrator missing run_v2)"
            ) from e
        return run_v2(params, progress_cb)
    return worker


# ── Backtest worker ──────────────────────────────────────────────────────────


def make_backtest_worker(get_router):
    """Strategy backtest. History pulled through router (cached)."""
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        ticker = (params.get("ticker") or "").upper().strip()
        if not ticker:
            raise ValueError("Missing 'ticker'")
        strategy_id = params.get("strategy_id", "buy_and_hold")
        start_date = params.get("start_date", "2025-01-01")
        end_date = params.get("end_date") or _today_str()
        initial_capital = float(params.get("initial_capital", 100_000))
        strat_params = params.get("params") or {}

        progress_cb(10, "拉取历史数据")
        from stock_trading_system.strategy.backtester import (
            BacktestEngine, make_router_history_fn,
        )
        history_fn = make_router_history_fn(get_router())
        engine = BacktestEngine(config={}, history_fn=history_fn)

        progress_cb(35, f"运行 {strategy_id} 策略")
        result = engine.run(
            ticker=ticker, strategy_id=strategy_id,
            start_date=start_date, end_date=end_date,
            initial_capital=initial_capital, params=strat_params,
        )

        progress_cb(95, "整理结果")
        # Shape result for the screen_results table-style storage in TaskStore
        # (backtest_results table has dedicated columns).
        return {
            "ticker": ticker,
            "strategy_id": strategy_id,
            "period": f"{start_date}~{end_date}",
            "initial_capital": initial_capital,
            "metrics": {
                "final_value": result.final_value,
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "num_trades": result.num_trades,
                "sharpe_ratio": result.sharpe_ratio,
            },
            "equity_curve": result.equity_curve,
            "benchmark_curve": result.benchmark_curve,
            "trades": result.trades,
        }
    return worker


def _today_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


# ── Echo (kept for smoke tests) ──────────────────────────────────────────────


def echo_worker(params: dict, progress_cb: ProgressCb) -> dict:
    progress_cb(10, "开始")
    progress_cb(50, "处理中")
    progress_cb(90, "即将完成")
    return {"echoed": params}


# ── Registration helper ──────────────────────────────────────────────────────


class WorkerDeps:
    """Container for lazy dependency getters."""

    def __init__(
        self,
        get_analyzer: Callable[[], Any] | None = None,
        get_screener: Callable[[], Any] | None = None,
        get_report_gen: Callable[[], Any] | None = None,
        get_strategy_engine: Callable[[], Any] | None = None,
        get_portfolio: Callable[[], Any] | None = None,
        get_router: Callable[[], Any] | None = None,
    ):
        self.get_analyzer = get_analyzer
        self.get_screener = get_screener
        self.get_report_gen = get_report_gen
        self.get_strategy_engine = get_strategy_engine
        self.get_portfolio = get_portfolio
        self.get_router = get_router


def register_default_workers(tm, deps: WorkerDeps) -> None:
    """Register every worker whose dependencies are available.

    Skips workers with missing deps rather than raising — makes it
    easy to stand up a test environment with only some deps wired.
    """
    tm.register("echo", echo_worker)

    if deps.get_analyzer and deps.get_strategy_engine and deps.get_portfolio \
            and deps.get_router:
        tm.register("analysis", make_analysis_worker(
            deps.get_analyzer, deps.get_strategy_engine,
            deps.get_portfolio, deps.get_router,
        ))

    if deps.get_screener:
        tm.register("screen", make_screen_worker(deps.get_screener))

    # ── V2 Screener (Agent + Guru driven) ──
    tm.register("screen_v2", make_screen_v2_worker())

    # ── Paper Trade (replay AI signals against historical prices) ──
    tm.register("paper_trade", make_paper_trade_worker())
    tm.register("paper_backfill", make_paper_backfill_worker())

    if deps.get_report_gen:
        tm.register("report", make_report_worker(deps.get_report_gen))

    if deps.get_router:
        tm.register("qwen_fundamentals",
                    make_qwen_fundamentals_worker(deps.get_router))
        tm.register("qwen_news",
                    make_qwen_news_worker(deps.get_router))
        tm.register("backtest", make_backtest_worker(deps.get_router))


# ─────────────────────────────────────────────────────────────────
# Screener V2 (Agent + Guru driven)
# ─────────────────────────────────────────────────────────────────

def make_screen_v2_worker():
    """Worker for V2 screener.

    Lazily imports + caches one ScreenerV2 instance per process.
    Persists results to screen_results_v2 table.
    """
    cache = {"instance": None, "store": None}

    def _get_screener():
        if cache["instance"] is None:
            from stock_trading_system.config import get_config
            from stock_trading_system.screener.v2 import ScreenerV2
            cfg = get_config()
            # Reuse the same LocalCache via a lightweight import path
            try:
                from stock_trading_system.data.local_cache import LocalCache
                db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
                cache_path = db_path.replace("portfolio.db", "cache.db")
                local = LocalCache(cache_path, config=cfg)
            except Exception:
                local = None
            cache["instance"] = ScreenerV2(cfg, local)
        return cache["instance"]

    def _get_store():
        if cache["store"] is None:
            from stock_trading_system.config import get_config
            from stock_trading_system.tasks.task_store import TaskStore
            cfg = get_config()
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            cache["store"] = TaskStore(db_path)
        return cache["store"]

    def worker(params, progress_cb):
        sv2 = _get_screener()
        result = sv2.run(params, progress_cb)
        # Persist
        store = _get_store()
        # task_id is not directly in params — TaskManager passes it via injection?
        # We use the inferred task_id from the calling context (set via params.__task_id__)
        task_id = params.get("__task_id__") or ""
        sid = store.save_screen_v2_result(
            task_id=task_id,
            market=params.get("market", "us"),
            strategy=params.get("strategy", "growth"),
            result=result,
            nl_query=params.get("nl_query"),
        )
        return {
            "result_ref": f"screen_results_v2:{sid}",
            "screen_v2_id": sid,
            "regime": (result.get("regime") or {}).get("label"),
            "picks_count": len(result.get("picks", [])),
        }
    return worker


# ─────────────────────────────────────────────────────────────────
# Paper Trade worker
# ─────────────────────────────────────────────────────────────────

def make_paper_trade_worker():
    """Worker for paper-trade session replay/run.

    Lazily builds one PaperTradeSimulator per process.
    Result is stored directly on the session row by the simulator; we
    return a result_ref pointing back to the session.
    """
    cache = {"sim": None, "store": None}

    def _get():
        if cache["sim"] is None:
            from stock_trading_system.config import get_config
            from stock_trading_system.strategy.paper_trader import (
                PaperTradeStore, PaperTradeSimulator, SignalLoader,
            )
            try:
                from stock_trading_system.data.local_cache import LocalCache
            except Exception:
                LocalCache = None  # noqa: N806
            cfg = get_config()
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            store = PaperTradeStore(db_path)
            signals = SignalLoader(db_path)
            local = None
            if LocalCache is not None:
                try:
                    cache_path = db_path.replace("portfolio.db", "cache.db")
                    local = LocalCache(cache_path, config=cfg)
                except Exception:
                    local = None
            cache["sim"] = PaperTradeSimulator(cfg, store, signals, local_cache=local)
            cache["store"] = store
        return cache["sim"], cache["store"]

    def worker(params, progress_cb):
        sim, _store = _get()
        session_id = int(params.get("session_id") or 0)
        if not session_id:
            raise ValueError("Missing 'session_id'")
        result = sim.run(session_id, progress_cb)
        metrics = result.get("metrics") or {}
        return {
            "result_ref": f"paper_trade_sessions:{session_id}",
            "session_id": session_id,
            "num_trades": metrics.get("num_trades", 0),
            "total_return_pct": metrics.get("total_return_pct", 0),
            "win_rate_pct": metrics.get("win_rate_pct", 0),
        }
    return worker


def make_paper_backfill_worker():
    """V2: replay analysis_history → per-ticker sessions + daily stats."""
    def worker(params, progress_cb):
        from stock_trading_system.config import get_config
        from stock_trading_system.portfolio.database import PortfolioDatabase
        from stock_trading_system.strategy.paper_trader import (
            PaperTradeStore, backfill_all,
        )
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        store = PaperTradeStore(db_path)
        pdb = PortfolioDatabase(db_path)
        result = backfill_all(store, pdb, cfg, progress_cb=progress_cb)
        return result
    return worker
