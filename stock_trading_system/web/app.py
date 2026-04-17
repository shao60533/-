"""Flask web application with API routes and WebSocket support."""

import json
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from stock_trading_system.config import load_config, get_config, save_config
from stock_trading_system.utils import get_logger

logger = get_logger("web")

socketio = SocketIO()

# Lazy-initialized shared components
_portfolio_mgr = None
_alert_monitor = None
_data_manager = None
_analyzer = None
_screener = None
_report_gen = None
_strategy_engine = None
_scheduler = None
_scheduler_thread = None
_task_manager = None
_task_store = None
_local_cache = None
_paper_store = None
_data_router = None


def _get_portfolio_mgr():
    global _portfolio_mgr
    if _portfolio_mgr is None:
        from stock_trading_system.portfolio.manager import PortfolioManager
        _portfolio_mgr = PortfolioManager(get_config())
    return _portfolio_mgr


def _get_alert_monitor():
    global _alert_monitor
    if _alert_monitor is None:
        from stock_trading_system.alerts.monitor import AlertMonitor
        _alert_monitor = AlertMonitor(get_config())
    return _alert_monitor


def _get_data_manager():
    global _data_manager
    if _data_manager is None:
        from stock_trading_system.data.data_manager import DataManager
        _data_manager = DataManager(get_config())
    return _data_manager


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from stock_trading_system.agents.analyzer import StockAnalyzer
        _analyzer = StockAnalyzer(get_config())
    return _analyzer


def _get_screener():
    global _screener
    if _screener is None:
        from stock_trading_system.screener.screener import StockScreener
        _screener = StockScreener(get_config())
    return _screener


def _get_report_gen():
    global _report_gen
    if _report_gen is None:
        from stock_trading_system.reports.report_generator import ReportGenerator
        _report_gen = ReportGenerator(get_config())
    return _report_gen


def _get_strategy_engine():
    global _strategy_engine
    if _strategy_engine is None:
        from stock_trading_system.strategy.strategy_engine import StrategyEngine
        _strategy_engine = StrategyEngine(get_config())
    return _strategy_engine


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from stock_trading_system.scheduler.task_scheduler import TaskScheduler
        _scheduler = TaskScheduler(get_config())
    return _scheduler


def _get_paper_store():
    """Lazy singleton for paper-trade store. Ensures default session exists."""
    global _paper_store
    if _paper_store is None:
        from stock_trading_system.strategy.paper_trader import PaperTradeStore
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        _paper_store = PaperTradeStore(db_path)
    return _paper_store


def _get_task_store():
    global _task_store
    if _task_store is None:
        from stock_trading_system.tasks.task_store import TaskStore
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        _task_store = TaskStore(db_path)
    return _task_store


def _get_task_manager():
    """Singleton TaskManager. Workers are registered on first access."""
    global _task_manager
    if _task_manager is None:
        from stock_trading_system.tasks.task_manager import TaskManager
        cfg = get_config()
        tasks_cfg = cfg.get("tasks", {}) or {}
        _task_manager = TaskManager(
            _get_task_store(),
            socketio=socketio,
            max_workers=int(tasks_cfg.get("max_workers", 3)),
            default_idempotency_window=int(tasks_cfg.get("idempotency_window", 60)),
        )
        _register_default_workers(_task_manager)
    return _task_manager


def _register_default_workers(tm):
    """Register worker functions for all known task types.

    Uses dependency injection via WorkerDeps so tests can swap providers.
    """
    from stock_trading_system.tasks.workers import (
        WorkerDeps, register_default_workers,
    )
    deps = WorkerDeps(
        get_analyzer=_get_analyzer,
        get_screener=_get_screener,
        get_report_gen=_get_report_gen,
        get_strategy_engine=_get_strategy_engine,
        get_portfolio=_get_portfolio_mgr,
        get_router=_get_data_router,
        socketio=socketio,
    )
    register_default_workers(tm, deps)


def _get_local_cache():
    global _local_cache
    if _local_cache is None:
        from stock_trading_system.data.local_cache import LocalCache
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        cache_path = db_path.replace("portfolio.db", "cache.db")
        _local_cache = LocalCache(cache_path, config=cfg)
    return _local_cache


_data_router = None
_cleanup_scheduler = None


def _get_data_router():
    """Lazy singleton DataRouter (Qwen-first with LocalCache).

    Coexists with the legacy _data_manager: call sites that need the
    V2 routing (workers, new analysis/news endpoints) use the router,
    while pre-existing routes continue to use DataManager until migrated.
    """
    global _data_router
    if _data_router is None:
        from stock_trading_system.data.data_router import DataRouter
        _data_router = DataRouter(get_config(), cache=_get_local_cache())
    return _data_router


def _get_cleanup_scheduler():
    """Lazy singleton task+cache cleanup scheduler.

    Started automatically by create_app(); exposed via /api/tasks/cleanup
    for manual one-shot invocation.
    """
    global _cleanup_scheduler
    if _cleanup_scheduler is None:
        from stock_trading_system.tasks.cleanup import TaskCleanupScheduler
        cfg = get_config()
        tasks_cfg = cfg.get("tasks", {}) or {}
        _cleanup_scheduler = TaskCleanupScheduler(
            store=_get_task_store(),
            retention_days=int(tasks_cfg.get("retention_days", 30)),
            interval_seconds=int(tasks_cfg.get("cleanup_interval", 6 * 3600)),
            cache=_get_local_cache(),
        )
    return _cleanup_scheduler


def _probe_providers() -> dict:
    """Quick reachability check for each enabled provider.

    Each probe runs in ≤8 seconds. We keep the calls intentionally cheap
    (1 ticker, no full chain) so that calling this endpoint after a deploy
    doesn't burn LLM tokens or hit rate limits.
    """
    import time as _time
    from stock_trading_system.utils.helpers import detect_market

    cfg = get_config()
    providers = cfg.get("providers", {}) or {}
    results: dict = {}

    def _probe(name: str, fn):
        start = _time.perf_counter()
        try:
            ok = bool(fn())
            return {
                "ok": ok,
                "latency_ms": int((_time.perf_counter() - start) * 1000),
                "error": None if ok else "no data",
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "latency_ms": int((_time.perf_counter() - start) * 1000),
                "error": str(e)[:200],
            }

    router = _get_data_router()

    if router.qwen.enabled:
        results["qwen"] = _probe("qwen", lambda: router.qwen.get_stock_price("AAPL"))

    if providers.get("yfinance_enabled", True):
        from stock_trading_system.data.yfinance_provider import YFinanceProvider
        yf = YFinanceProvider()
        results["yfinance"] = _probe("yfinance", lambda: yf.get_stock_price("AAPL"))

    if providers.get("akshare_enabled", True):
        from stock_trading_system.data.akshare_provider import AkShareProvider
        ak = AkShareProvider()
        results["akshare"] = _probe("akshare", lambda: ak.get_stock_price("600519"))

    if providers.get("polygon_enabled", False):
        from stock_trading_system.data.polygon_provider import PolygonProvider
        pg = PolygonProvider(cfg)
        results["polygon"] = _probe("polygon", lambda: pg.get_stock_price("AAPL"))

    if providers.get("ib_enabled", False):
        # Don't actually try to connect to IB from a probe — too slow if it
        # times out. Just report whether IB is configured and a TWS host
        # is reachable on TCP. Keep it dumb.
        ib_cfg = cfg.get("ib", {}) or {}
        results["ib"] = {
            "ok": False,
            "latency_ms": 0,
            "error": (
                "IB requires a local TWS process — not testable from a "
                "cloud probe. Run on a machine with TWS to use IB."
            ),
            "host": ib_cfg.get("host"), "port": ib_cfg.get("port"),
        }

    return results


def _mask_secret(value: str, keep: int = 4) -> str:
    """Mask a sensitive string, keeping only the last `keep` characters."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def create_app(config_path=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "stock-trading-system-secret"

    load_config(config_path)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # ── Page Routes ─────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Dashboard API ───────────────────────────────────────────────────

    @app.route("/api/dashboard")
    def api_dashboard():
        pm = _get_portfolio_mgr()
        pnl = pm.get_pnl()
        holdings = pm.get_holdings()
        alerts = _get_alert_monitor().list_alerts()

        # Auto-snapshot: save today's data if no snapshot exists yet
        # (uses already-fetched pnl, avoids double price lookup)
        import json as _json
        from datetime import datetime as _dt
        from stock_trading_system.portfolio.models import DailySnapshot
        today_str = _dt.now().strftime("%Y-%m-%d")
        history = pm.get_history(days=30)
        if not history or history[0].get("date") != today_str:
            try:
                snap = DailySnapshot(
                    date=today_str,
                    total_value=pnl["total_value"],
                    total_cost=pnl["total_cost"],
                    pnl=pnl["total_pnl"],
                    pnl_pct=pnl["total_pnl_pct"],
                    positions_json=_json.dumps(holdings, default=str),
                )
                pm._db.save_snapshot(snap)
                history = pm.get_history(days=30)
                logger.info("Auto-snapshot for %s (value=%.2f)",
                            today_str, pnl["total_value"])
            except Exception as e:
                logger.warning("Auto-snapshot failed: %s", e)

        return jsonify({
            "pnl": pnl,
            "holdings": holdings,
            "alerts_count": len(alerts),
            "history": history,
        })

    # ── Portfolio API ───────────────────────────────────────────────────

    @app.route("/api/portfolio/holdings")
    def api_holdings():
        return jsonify(_get_portfolio_mgr().get_holdings())

    @app.route("/api/portfolio/add", methods=["POST"])
    def api_portfolio_add():
        data = request.json
        from stock_trading_system.utils.helpers import detect_market
        pm = _get_portfolio_mgr()
        ticker = data["ticker"].upper()
        pm.add_position(
            ticker, float(data["shares"]), float(data["price"]),
            market=detect_market(ticker),
            date=data.get("date"), notes=data.get("notes", ""),
        )
        return jsonify({"ok": True, "message": f"BUY {data['shares']} {ticker} @ {data['price']}"})

    @app.route("/api/portfolio/sell", methods=["POST"])
    def api_portfolio_sell():
        data = request.json
        pm = _get_portfolio_mgr()
        ticker = data["ticker"].upper()
        shares = float(data["shares"])
        # Validate: must have enough shares (direct DB check, no price fetch)
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        pos = PortfolioDatabase(db_path).get_position(ticker)
        if not pos:
            return jsonify({"ok": False, "error": f"No position in {ticker}"}), 400
        if shares > pos.shares:
            return jsonify({"ok": False, "error": f"Insufficient shares: have {pos.shares}, want to sell {shares}"}), 400
        pm.sell_position(
            ticker, shares, float(data["price"]),
            date=data.get("date"), notes=data.get("notes", ""),
        )
        return jsonify({"ok": True, "message": f"SELL {shares} {ticker} @ {data['price']}"})

    @app.route("/api/portfolio/transactions")
    def api_transactions():
        ticker = request.args.get("ticker")
        return jsonify(_get_portfolio_mgr().get_transactions(ticker=ticker))

    @app.route("/api/portfolio/pnl")
    def api_pnl():
        return jsonify(_get_portfolio_mgr().get_pnl())

    @app.route("/api/portfolio/allocation")
    def api_allocation():
        return jsonify(_get_portfolio_mgr().get_allocation())

    @app.route("/api/portfolio/history")
    def api_history():
        days = request.args.get("days", 30, type=int)
        return jsonify(_get_portfolio_mgr().get_history(days=days))

    # ── Analysis API ────────────────────────────────────────────────────

    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        data = request.json
        ticker = data["ticker"].upper()
        date = data.get("date")
        if not date:
            from stock_trading_system.utils.helpers import today_str
            date = today_str()

        # Run in background thread, emit result via WebSocket
        def run_analysis():
            try:
                socketio.emit("analysis_status", {"ticker": ticker, "status": "running"})

                def _progress(step, status):
                    socketio.emit("analysis_step", {"ticker": ticker, "step": step, "status": status})

                analyzer = _get_analyzer()
                result = analyzer.analyze(ticker, date, progress_callback=_progress)

                # Also generate strategy advice
                advice = None
                try:
                    engine = _get_strategy_engine()
                    pm = _get_portfolio_mgr()
                    holdings = pm.get_holdings()
                    # Get current price for strategy calculation
                    price_data = _get_data_manager().get_price(ticker)
                    current_price = None
                    if price_data:
                        current_price = price_data.get("last") or price_data.get("close")
                    advice_obj = engine.generate_advice(result, holdings, current_price)
                    advice = {
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
                except Exception as e:
                    logger.warning("Strategy advice failed: %s", e)

                result_data = {
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
                socketio.emit("analysis_result", result_data)

                # Save to history
                new_analysis_id = None
                try:
                    import json as _json
                    from stock_trading_system.portfolio.database import PortfolioDatabase
                    db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                    db = PortfolioDatabase(db_path)
                    new_analysis_id = db.save_analysis({
                        **result_data,
                        "advice_json": _json.dumps(advice, ensure_ascii=False) if advice else "",
                        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    logger.info("Analysis saved to history: %s (id=%s)", ticker, new_analysis_id)
                except Exception as save_err:
                    logger.warning("Failed to save analysis history: %s", save_err)

                # Auto-track to active paper-trade sessions (v1.2)
                if new_analysis_id and result_data.get("signal") != "ERROR":
                    try:
                        from stock_trading_system.strategy.paper_trader import (
                            auto_track_analysis, process_analysis,
                        )
                        paper_store = _get_paper_store()
                        tracked_ids = auto_track_analysis(
                            paper_store,
                            analysis_id=new_analysis_id,
                            ticker=ticker,
                            signal=result_data.get("signal", ""),
                            advice=advice,
                        )

                        # V2: route to per-ticker session executor
                        # Look up current price from router for entry-range check
                        current_price = None
                        try:
                            router = _get_data_router()
                            pdata = router.get_price(ticker) if router else None
                            if pdata:
                                current_price = pdata.get("last") or pdata.get("close")
                        except Exception:
                            pass
                        # Optional: pass qwen provider for LLM-based plan extraction
                        qwen = None
                        try:
                            router = _get_data_router()
                            qwen = getattr(router, "_qwen", None) if router else None
                        except Exception:
                            qwen = None

                        ana_for_parser = {
                            "signal": result_data.get("signal", ""),
                            "trade_decision": result_data.get("trade_decision", ""),
                            "risk_assessment": result_data.get("risk_assessment", ""),
                            "investment_debate": result_data.get("investment_debate", ""),
                            "market_report": result_data.get("market_report", ""),
                            "advice_json": advice,
                        }
                        v2_res = process_analysis(
                            paper_store,
                            analysis_id=new_analysis_id,
                            ticker=ticker,
                            analysis_date=__import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                            signal=result_data.get("signal", ""),
                            advice=advice,
                            current_price=current_price,
                            analysis_blob=ana_for_parser,
                            qwen_provider=qwen,
                        )

                        if tracked_ids or v2_res.get("ok"):
                            socketio.emit("analysis_tracked", {
                                "analysis_id": new_analysis_id,
                                "ticker": ticker,
                                "tracked_ids": tracked_ids,
                                "v2_session_id": v2_res.get("session_id"),
                                "v2_plan_id": v2_res.get("plan_id"),
                                "v2_parse_method": v2_res.get("parse_method"),
                                "v2_orders": v2_res.get("num_orders"),
                            })
                    except Exception as tr_err:
                        logger.warning("Auto-track failed (non-fatal): %s", tr_err)
            except Exception as e:
                import traceback as _tb
                import datetime as _dt
                error_msg = str(e)
                tb_str = _tb.format_exc()
                logger.error("Analysis failed for %s: %s\n%s", ticker, error_msg, tb_str)
                socketio.emit("analysis_error", {"ticker": ticker, "error": error_msg})
                # Save failure record so it appears in analysis history
                try:
                    from stock_trading_system.portfolio.database import PortfolioDatabase
                    db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                    db = PortfolioDatabase(db_path)
                    db.save_analysis({
                        "ticker": ticker,
                        "date": date,
                        "signal": "ERROR",
                        "trade_decision": f"分析失败: {error_msg}\n\n{tb_str}",
                        "created_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception as save_err:
                    logger.warning("Failed to save error record: %s", save_err)

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()
        return jsonify({"ok": True, "message": f"Analysis started for {ticker}"})

    # ── Screener API ────────────────────────────────────────────────────

    @app.route("/api/screen", methods=["POST"])
    def api_screen():
        data = request.json
        market = data.get("market", "us")
        strategy = data.get("strategy", "growth")

        def run_screen():
            try:
                socketio.emit("screen_status", {"status": "running", "market": market, "strategy": strategy})
                screener = _get_screener()
                results = screener.screen(market=market, strategy=strategy)
                socketio.emit("screen_result", {"results": results, "market": market, "strategy": strategy})
            except Exception as e:
                logger.error("Screening failed: %s", e)
                socketio.emit("screen_error", {"error": str(e)})

        thread = threading.Thread(target=run_screen, daemon=True)
        thread.start()
        return jsonify({"ok": True, "message": f"Screening {market} with {strategy} strategy"})

    # ─────────────────────────────────────────────────────────────────
    # Screener V2 API (Agent + Guru driven)
    # ─────────────────────────────────────────────────────────────────

    @app.route("/api/screen/v2/submit", methods=["POST"])
    def api_screen_v2_submit():
        """Submit V2 screening task. Returns {task_id}."""
        data = request.json or {}
        params = {
            "market": data.get("market", "us"),
            "strategy": data.get("strategy", "growth"),
            "enabled_gurus": data.get("enabled_gurus") or ["buffett", "graham", "lynch", "oneil"],
            "nl_query": data.get("nl_query") or None,
            "final_count": int(data.get("final_count", 5)),
            "max_universe": int(data.get("max_universe", 100)),
        }
        try:
            tm = _get_task_manager()
            task = tm.submit("screen_v2", params)
            return jsonify({"ok": True, "task_id": task["id"], "task": task})
        except Exception as e:
            logger.error("Screen V2 submit failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/screen/v2/result/<int:result_id>")
    def api_screen_v2_result(result_id: int):
        """Get a V2 screen result by id."""
        store = _get_task_store()
        result = store.get_screen_v2_result(result_id)
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    @app.route("/api/screen/v2/result/by_task/<task_id>")
    def api_screen_v2_result_by_task(task_id: str):
        """Get V2 result by task_id."""
        store = _get_task_store()
        # Inspect tasks table
        task = store.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        ref = task.get("result_ref") or ""
        if not ref.startswith("screen_results_v2:"):
            return jsonify({"error": "Result not yet available", "task": task}), 202
        try:
            sid = int(ref.split(":", 1)[1])
        except Exception:
            return jsonify({"error": "Bad result_ref", "task": task}), 500
        result = store.get_screen_v2_result(sid)
        if not result:
            return jsonify({"error": "Result row missing"}), 404
        return jsonify(result)

    @app.route("/api/screen/v2/history")
    def api_screen_v2_history():
        """List recent V2 screening runs (lightweight)."""
        limit = int(request.args.get("limit", 50))
        store = _get_task_store()
        return jsonify(store.list_screen_v2_history(limit=limit))

    @app.route("/api/screen/v2/gurus")
    def api_screen_v2_gurus():
        """Return metadata for all 8 gurus (4 implemented + 4 placeholders)."""
        from stock_trading_system.screener.v2 import all_guru_metadata
        return jsonify(all_guru_metadata())

    # ─────────────────────────────────────────────────────────────────
    # Paper Trade API (v1.2 — AI analysis effectiveness tracking)
    # ─────────────────────────────────────────────────────────────────

    @app.route("/api/paper/sessions", methods=["POST"])
    def api_paper_create_session():
        """Create a paper-trade session (does not run immediately)."""
        data = request.json or {}
        try:
            name = data.get("name") or f"Session {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
            mode = data.get("mode", "replay")
            if mode not in ("replay", "live"):
                return jsonify({"ok": False, "error": "mode must be replay|live"}), 400
            start_capital = float(data.get("start_capital", 100000))
            start_date = data.get("start_date")
            end_date = data.get("end_date")
            if not start_date:
                return jsonify({"ok": False, "error": "start_date required"}), 400
            if mode == "replay" and not end_date:
                return jsonify({"ok": False, "error": "end_date required for replay"}), 400

            cfg = {
                "filters": data.get("filters") or {},
                "sizing": data.get("sizing") or {},
                "exit_rules": data.get("exit_rules") or {},
                "cost": data.get("cost") or {},
                "benchmark": data.get("benchmark", "SPY"),
            }
            store = _get_paper_store()
            sid = store.create_session(
                name=name, mode=mode,
                start_capital=start_capital,
                start_date=start_date, end_date=end_date,
                config=cfg, auto_track=bool(data.get("auto_track", False)),
            )
            return jsonify({"ok": True, "session_id": sid, "session": store.get_session(sid)})
        except Exception as e:
            logger.error("Create paper session failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/paper/sessions/<int:session_id>/run", methods=["POST"])
    def api_paper_run(session_id: int):
        """Submit an async paper-trade simulation task for this session."""
        try:
            tm = _get_task_manager()
            task = tm.submit("paper_trade", {"session_id": session_id})
            return jsonify({"ok": True, "task_id": task["id"], "task": task})
        except Exception as e:
            logger.error("Paper run submit failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/paper/sessions")
    def api_paper_list_sessions():
        store = _get_paper_store()
        return jsonify(store.list_sessions(limit=int(request.args.get("limit", 100))))

    @app.route("/api/paper/sessions/<int:session_id>")
    def api_paper_session_detail(session_id: int):
        store = _get_paper_store()
        sess = store.get_session(session_id)
        if not sess:
            return jsonify({"error": "Not found"}), 404
        return jsonify(sess)

    @app.route("/api/paper/sessions/<int:session_id>/equity")
    def api_paper_equity(session_id: int):
        store = _get_paper_store()
        return jsonify(store.list_equity(session_id))

    @app.route("/api/paper/sessions/<int:session_id>/trades")
    def api_paper_trades(session_id: int):
        store = _get_paper_store()
        limit = int(request.args.get("limit", 500))
        return jsonify(store.list_trades(session_id, limit=limit))

    @app.route("/api/paper/sessions/<int:session_id>/tracked")
    def api_paper_session_tracked(session_id: int):
        store = _get_paper_store()
        status = request.args.get("status")
        return jsonify(store.list_tracked_by_session(session_id, status=status,
                                                     limit=int(request.args.get("limit", 500))))

    @app.route("/api/paper/sessions/<int:session_id>", methods=["DELETE"])
    def api_paper_delete_session(session_id: int):
        store = _get_paper_store()
        ok = store.delete_session(session_id)
        if not ok:
            return jsonify({"ok": False, "error": "Cannot delete (system session or missing)"}), 400
        return jsonify({"ok": True})

    @app.route("/api/paper/track", methods=["POST"])
    def api_paper_track_create():
        """Manual track: add an analysis to a session's pending queue."""
        data = request.json or {}
        analysis_id = data.get("analysis_id")
        session_id = data.get("session_id")
        if not analysis_id or not session_id:
            return jsonify({"ok": False, "error": "analysis_id + session_id required"}), 400

        # Look up ticker via analysis_history
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        ana = db.get_analysis_by_id(analysis_id)
        if not ana:
            return jsonify({"ok": False, "error": "Analysis not found"}), 404

        store = _get_paper_store()
        from stock_trading_system.strategy.paper_trader import manual_track
        tid = manual_track(store, analysis_id=analysis_id, ticker=ana["ticker"],
                           session_id=int(session_id), notes=data.get("notes"))
        if tid is None:
            return jsonify({"ok": False, "error": "Failed to create tracking record"}), 500
        return jsonify({"ok": True, "tracked_id": tid})

    @app.route("/api/paper/track/<int:tracked_id>", methods=["DELETE"])
    def api_paper_track_delete(tracked_id: int):
        store = _get_paper_store()
        ok = store.delete_tracked(tracked_id)
        if not ok:
            return jsonify({"ok": False, "error": "Only pending records can be cancelled"}), 400
        return jsonify({"ok": True})

    @app.route("/api/paper/track/by_analysis/<int:analysis_id>")
    def api_paper_track_by_analysis(analysis_id: int):
        store = _get_paper_store()
        return jsonify(store.list_tracked_by_analysis(analysis_id))

    @app.route("/api/paper/track/by_ticker/<ticker>")
    def api_paper_track_by_ticker(ticker: str):
        """Full tracking timeline for a ticker (includes aggregate stats)."""
        store = _get_paper_store()
        from stock_trading_system.strategy.paper_trader import ticker_summary
        return jsonify(ticker_summary(store, ticker))

    # ── Paper Trade V2 (per-ticker) ─────────────────────────────────────

    @app.route("/api/paper/tickers")
    def api_paper_tickers():
        """List every ticker session with summary metrics (for card grid)."""
        store = _get_paper_store()
        sessions = store.list_ticker_sessions()
        out = []
        for s in sessions:
            sid = int(s["id"])
            last = store.last_daily_stat(sid)
            latest_evt = store.latest_strategy_event(sid)
            events = store.list_strategy_events(sid)
            # Mini sparkline: last 30 daily total_values
            dailies = store.list_daily_stats(sid, limit=1000)
            spark = [float(d["total_value"]) for d in dailies[-30:]]
            # Hit rate: BUY events where the price moved up in the next 5 daily bars
            buys = [e for e in events
                    if (e.get("new_signal") or "").upper() in ("BUY", "OVERWEIGHT")]
            hits, total = 0, 0
            for e in buys:
                # Find next 5 daily close prices after the event date
                fwd = [d for d in dailies if d["date"] > e["event_date"]][:5]
                if len(fwd) >= 1 and e.get("price"):
                    total += 1
                    if fwd[-1]["close_price"] > e["price"]:
                        hits += 1
            out.append({
                "id": sid,
                "ticker": s["ticker"],
                "status": s["status"],
                "start_date": s["start_date"],
                "last_eod": s.get("last_eod_date"),
                "current_signal": latest_evt["new_signal"] if latest_evt else None,
                "current_action": latest_evt["action"] if latest_evt else None,
                "total_value": float(last["total_value"]) if last else float(s["start_capital"]),
                "cum_pnl_pct": float(last["cum_pnl_pct"]) if last else 0,
                "position_shares": float(last["position_shares"]) if last else 0,
                "close_price": float(last["close_price"]) if last and last.get("close_price") else None,
                "num_events": len(events),
                "hit_rate": (hits / total) if total else None,
                "hit_pretty": f"{hits}/{total}" if total else "—",
                "sparkline": spark,
            })
        return jsonify(out)

    @app.route("/api/paper/tickers/<ticker>")
    def api_paper_ticker_detail(ticker: str):
        """Full detail bundle: session + events + dailies + trades + plans + orders."""
        store = _get_paper_store()
        sess = store.find_session_by_ticker(ticker.upper())
        if not sess:
            return jsonify({"error": "No session for ticker"}), 404
        sid = int(sess["id"])
        events = store.list_strategy_events(sid)
        dailies = store.list_daily_stats(sid, limit=1000)
        trades = store.list_trades(sid, limit=500)
        active_plan = store.get_active_plan(sid)
        all_plans = store.list_plans(sid)
        # Pending orders under the active plan
        active_orders = []
        if active_plan:
            active_orders = store.list_orders(plan_id=active_plan["id"])
        # For plan history: include each plan's orders
        plan_history = []
        for p in all_plans:
            p_orders = store.list_orders(plan_id=p["id"])
            plan_history.append({**p, "orders": p_orders})
        # Attach analysis summary for latest event
        latest = events[0] if events else None
        latest_advice = None
        if latest:
            try:
                from stock_trading_system.portfolio.database import PortfolioDatabase
                db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                ana = PortfolioDatabase(db_path).get_analysis_by_id(
                    latest["analysis_id"])
                if ana and ana.get("advice_json"):
                    import json as _j
                    try:
                        latest_advice = _j.loads(ana["advice_json"])
                    except Exception:
                        latest_advice = None
            except Exception:
                pass
        return jsonify({
            "session": sess,
            "events": events,
            "dailies": dailies,
            "trades": trades,
            "latest_advice": latest_advice,
            "active_plan": active_plan,
            "active_orders": active_orders,
            "plan_history": plan_history,
        })

    @app.route("/api/paper/tickers/<ticker>/eod", methods=["POST"])
    def api_paper_ticker_eod(ticker: str):
        """Manually run EOD update for one ticker session."""
        store = _get_paper_store()
        sess = store.find_session_by_ticker(ticker.upper())
        if not sess:
            return jsonify({"ok": False, "error": "Not found"}), 404
        try:
            from stock_trading_system.strategy.paper_trader import DailyUpdater
            updater = DailyUpdater(get_config(), store)
            rows = updater.update_session(int(sess["id"]))
            return jsonify({"ok": True, "new_rows": len(rows)})
        except Exception as e:
            logger.error("Manual EOD failed for %s: %s", ticker, e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/paper/backfill", methods=["POST"])
    def api_paper_backfill():
        """Replay analysis_history → per-ticker sessions. Async via TaskManager."""
        try:
            tm = _get_task_manager()
            task = tm.submit("paper_backfill", {})
            return jsonify({"ok": True, "task_id": task["id"], "task": task})
        except Exception as e:
            logger.error("Backfill submit failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── Alerts API ──────────────────────────────────────────────────────

    @app.route("/api/alerts")
    def api_alerts():
        return jsonify(_get_alert_monitor().list_alerts())

    @app.route("/api/alerts/add", methods=["POST"])
    def api_alert_add():
        data = request.json
        monitor = _get_alert_monitor()
        monitor.add_alert(data["ticker"].upper(), data["condition"], float(data["threshold"]))
        return jsonify({"ok": True, "message": f"Alert added: {data['ticker']} {data['condition']} {data['threshold']}"})

    @app.route("/api/alerts/remove", methods=["POST"])
    def api_alert_remove():
        data = request.json
        _get_alert_monitor().remove_alert(int(data["id"]))
        return jsonify({"ok": True})

    @app.route("/api/alerts/check", methods=["POST"])
    def api_alert_check():
        triggered = _get_alert_monitor().check_alerts()
        return jsonify({"triggered": triggered})

    @app.route("/api/alerts/history")
    def api_alert_history():
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        ticker = request.args.get("ticker")
        limit = int(request.args.get("limit", 50))
        return jsonify(db.get_alert_history(ticker=ticker, limit=limit))

    # ── Analysis History API ──────────────────────────────────────────────

    @app.route("/api/history")
    def api_analysis_history():
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        ticker = request.args.get("ticker")
        records = db.get_analysis_history(ticker=ticker)
        # Return lightweight list (no full report content) for fast loading
        summary = [{
            "id": r["id"], "ticker": r["ticker"], "date": r["date"],
            "signal": r["signal"], "created_at": r["created_at"],
        } for r in records]
        return jsonify(summary)

    @app.route("/api/history/<int:analysis_id>")
    def api_analysis_detail(analysis_id):
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        record = db.get_analysis_by_id(analysis_id)
        if record:
            return jsonify(record)
        return jsonify({"error": "Not found"}), 404

    # ── Reports API ─────────────────────────────────────────────────────

    @app.route("/api/report", methods=["POST"])
    def api_report():
        data = request.json
        report_type = data.get("type", "daily")
        ticker = data.get("ticker")
        gen = _get_report_gen()

        if report_type == "daily":
            content = gen.daily_report()
        elif report_type == "weekly":
            content = gen.weekly_report()
        elif report_type == "monthly":
            content = gen.monthly_report()
        elif report_type == "stock" and ticker:
            content = gen.stock_report(ticker.upper())
        else:
            return jsonify({"error": "Invalid report type"}), 400

        return jsonify({"content": content, "type": report_type})

    # ── Price Lookup ────────────────────────────────────────────────────

    @app.route("/api/price/<ticker>")
    def api_price(ticker):
        dm = _get_data_manager()
        price = dm.get_price(ticker.upper())
        if price:
            return jsonify(price)
        return jsonify({"error": "Price not available"}), 404

    @app.route("/api/quote/<ticker>")
    def api_quote(ticker):
        """Real-time quote with basic metadata."""
        from stock_trading_system.utils.helpers import detect_market
        t = ticker.upper()
        dm = _get_data_manager()
        price = dm.get_price(t)
        if not price:
            return jsonify({"error": "Quote not available"}), 404
        return jsonify({
            "ticker": t,
            "market": detect_market(t),
            "price": price,
        })

    # ── Chart / Fundamentals / News ─────────────────────────────────────

    @app.route("/api/chart/<ticker>")
    def api_chart(ticker):
        """Return OHLCV data for K-line rendering.

        Query params:
            period: 1d, 5d, 1mo, 3mo, 6mo, 1y (default 1mo)
            interval: 1d, 1h, 5m (default 1d)
        """
        period = request.args.get("period", "1mo")
        interval = request.args.get("interval", "1d")
        t = ticker.upper()

        try:
            df = _get_data_manager().get_history(t, period=period, interval=interval)
        except Exception as e:
            logger.warning("Chart data failed for %s: %s", t, e)
            return jsonify({"error": str(e)}), 500

        if df is None or len(df) == 0:
            return jsonify({"error": "No chart data"}), 404

        # Normalize column names to lowercase for lookup
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        rows = []
        for idx, row in df.iterrows():
            try:
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            except Exception:
                date_str = str(idx)
            rows.append({
                "date": date_str,
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
            })
        return jsonify({
            "ticker": t,
            "period": period,
            "interval": interval,
            "data": rows,
        })

    @app.route("/api/fundamentals/<ticker>")
    def api_fundamentals(ticker):
        """Return fundamental indicators for a stock."""
        t = ticker.upper()
        try:
            data = _get_data_manager().get_fundamentals(t)
        except Exception as e:
            logger.warning("Fundamentals failed for %s: %s", t, e)
            return jsonify({"error": str(e)}), 500
        if not data:
            return jsonify({"error": "Fundamentals not available"}), 404
        return jsonify(data)

    @app.route("/api/news/<ticker>")
    def api_news(ticker):
        """Return recent news for a stock."""
        t = ticker.upper()
        try:
            news = _get_data_manager().get_news(t)
        except Exception as e:
            logger.warning("News failed for %s: %s", t, e)
            return jsonify({"error": str(e)}), 500
        return jsonify(news or [])

    # ── Portfolio Extras ────────────────────────────────────────────────

    @app.route("/api/portfolio/update_cost", methods=["POST"])
    def api_portfolio_update_cost():
        data = request.json or {}
        ticker = data.get("ticker", "").upper()
        try:
            avg_cost = float(data.get("avg_cost"))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid avg_cost"}), 400
        if not ticker:
            return jsonify({"error": "Missing ticker"}), 400
        pm = _get_portfolio_mgr()
        pm.update_cost(ticker, avg_cost)
        return jsonify({"ok": True, "message": f"Updated {ticker} avg cost to {avg_cost}"})

    @app.route("/api/portfolio/snapshot", methods=["POST"])
    def api_portfolio_snapshot():
        pm = _get_portfolio_mgr()
        pm.take_snapshot()
        return jsonify({"ok": True, "message": "Snapshot saved"})

    # ── Scheduler Control ───────────────────────────────────────────────

    @app.route("/api/scheduler/status")
    def api_scheduler_status():
        global _scheduler_thread
        sched = _get_scheduler()
        alive = _scheduler_thread is not None and _scheduler_thread.is_alive()
        return jsonify({
            "running": bool(alive and sched.is_running),
            "thread_alive": bool(alive),
            "alert_interval": sched._alert_interval,
        })

    @app.route("/api/scheduler/start", methods=["POST"])
    def api_scheduler_start():
        global _scheduler_thread
        sched = _get_scheduler()
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return jsonify({"ok": True, "message": "Scheduler already running"})
        _scheduler_thread = threading.Thread(target=sched.start, daemon=True)
        _scheduler_thread.start()
        logger.info("Scheduler started via web API")
        return jsonify({"ok": True, "message": "Scheduler started"})

    @app.route("/api/scheduler/stop", methods=["POST"])
    def api_scheduler_stop():
        global _scheduler_thread
        if _scheduler is None or _scheduler_thread is None or not _scheduler_thread.is_alive():
            return jsonify({"ok": True, "message": "Scheduler not running"})
        _scheduler.stop()
        _scheduler_thread.join(timeout=3)
        _scheduler_thread = None
        logger.info("Scheduler stopped via web API")
        return jsonify({"ok": True, "message": "Scheduler stopped"})

    # ── Settings (read-only) ────────────────────────────────────────────

    @app.route("/api/settings")
    def api_settings():
        """Return a masked view of the current config + runtime status."""
        cfg = get_config()
        gemini = cfg.get("gemini", {}) or {}
        polygon = cfg.get("polygon", {}) or {}
        ib = cfg.get("ib", {}) or {}
        qwen = cfg.get("qwen", {}) or {}
        telegram = (cfg.get("alerts", {}) or {}).get("telegram", {}) or {}
        email = (cfg.get("alerts", {}) or {}).get("email", {}) or {}
        portfolio_cfg = cfg.get("portfolio", {}) or {}

        qwen_active = bool(qwen.get("enabled") and qwen.get("api_key"))

        # Data source liveness (best-effort, non-blocking checks)
        dm_status = {}
        try:
            dm_status["ib_enabled"] = bool(ib.get("enabled"))
            dm_status["polygon_configured"] = bool(polygon.get("api_key"))
            dm_status["akshare"] = True  # no-key provider, always usable
            dm_status["qwen_enabled"] = qwen_active
        except Exception:
            pass

        return jsonify({
            "gemini": {
                "model": gemini.get("model", ""),
                "deep_think_model": gemini.get("deep_think_model", ""),
                "thinking_level": gemini.get("thinking_level", ""),
                "api_key_masked": _mask_secret(gemini.get("api_key", "")),
            },
            "polygon": {
                "api_key_masked": _mask_secret(polygon.get("api_key", "")),
            },
            "qwen": {
                "enabled": qwen_active,
                "model": qwen.get("model", ""),
                "base_url": qwen.get("base_url", ""),
                "api_key_masked": _mask_secret(qwen.get("api_key", "")),
            },
            "ib": {
                "host": ib.get("host", ""),
                "port": ib.get("port", ""),
                "client_id": ib.get("client_id", ""),
                "enabled": bool(ib.get("enabled")),
            },
            "telegram": {
                "bot_token_masked": _mask_secret(telegram.get("bot_token", "")),
                "chat_id": telegram.get("chat_id", ""),
            },
            "email": {
                "smtp_host": email.get("smtp_host", ""),
                "smtp_port": email.get("smtp_port", ""),
                "username": email.get("username", ""),
                "password_masked": _mask_secret(email.get("password", "")),
                "to_address": email.get("to_address", ""),
            },
            "portfolio": {
                "db_path": portfolio_cfg.get("db_path", ""),
            },
            "data_sources": dm_status,
        })

    # ── Backtest API ────────────────────────────────────────────────────

    _backtester = None

    def _get_backtester():
        nonlocal _backtester
        if _backtester is None:
            from stock_trading_system.strategy.backtester import BacktestEngine
            _backtester = BacktestEngine(get_config())
        return _backtester

    @app.route("/api/backtest/strategies")
    def api_backtest_strategies():
        return jsonify(_get_backtester().list_strategies())

    @app.route("/api/backtest/run", methods=["POST"])
    def api_backtest_run():
        data = request.json or {}
        ticker = data.get("ticker", "").upper()
        strategy_id = data.get("strategy_id", "sma_crossover")
        start_date = data.get("start_date", "2025-01-01")
        end_date = data.get("end_date", "")
        initial_capital = float(data.get("initial_capital", 100000))
        params = data.get("params", {})

        if not end_date:
            from stock_trading_system.utils.helpers import today_str
            end_date = today_str()

        try:
            result = _get_backtester().run(
                ticker=ticker, strategy_id=strategy_id,
                start_date=start_date, end_date=end_date,
                initial_capital=initial_capital, params=params,
            )
            import dataclasses
            return jsonify(dataclasses.asdict(result))
        except Exception as e:
            logger.error("Backtest failed: %s", e)
            return jsonify({"error": str(e)}), 400

    # ── Settings Write ─────────────────────────────────────────────────

    WRITABLE_KEYS = {
        "gemini.api_key", "gemini.model", "gemini.deep_think_model", "gemini.thinking_level",
        "polygon.api_key",
        "qwen.api_key", "qwen.model", "qwen.enabled", "qwen.base_url",
        "ib.host", "ib.port", "ib.enabled", "ib.client_id",
        "alerts.telegram.bot_token", "alerts.telegram.chat_id",
        "alerts.email.smtp_host", "alerts.email.smtp_port",
        "alerts.email.username", "alerts.email.password", "alerts.email.to_address",
    }

    @app.route("/api/settings", methods=["PUT"])
    def api_settings_update():
        """Update whitelisted config keys. Body: {key: value, ...} using dot notation."""
        data = request.json or {}
        updates = {}
        rejected = []
        for key, value in data.items():
            if key not in WRITABLE_KEYS:
                rejected.append(key)
                continue
            parts = key.split(".")
            node = updates
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value
        try:
            save_config(updates)
            logger.info("Settings updated: %s", list(data.keys()))
        except Exception as e:
            logger.error("Failed to save settings: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
        resp = {"ok": True, "updated": [k for k in data if k in WRITABLE_KEYS]}
        if rejected:
            resp["rejected"] = rejected
        return jsonify(resp)

    # ── Health Check ──────────────────────────────────────────────────

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok"})

    # ── Tasks API (async task center) ───────────────────────────────────

    @app.route("/api/tasks/submit", methods=["POST"])
    def api_task_submit():
        """Submit an async task. Returns the persisted task record.

        Body: {"type": "<task_type>", "params": {...}, "title"?: "..."}
        """
        data = request.json or {}
        task_type = (data.get("type") or "").strip()
        params = data.get("params") or {}
        title = data.get("title")
        if not task_type:
            return jsonify({"error": "Missing task type"}), 400
        tm = _get_task_manager()
        if task_type not in tm.registered_types():
            return jsonify({
                "error": f"Unknown task type: {task_type}",
                "registered": tm.registered_types(),
            }), 400
        try:
            task = tm.submit(task_type, params, title=title)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to submit task")
            return jsonify({"error": str(e)}), 500
        return jsonify(task)

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_list():
        tm = _get_task_manager()
        task_type = request.args.get("type")
        status = request.args.get("status")
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        return jsonify({
            "items": tm.list(task_type=task_type, status=status,
                             limit=limit, offset=offset),
            "limit": limit,
            "offset": offset,
        })

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def api_task_detail(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)

    @app.route("/api/tasks/<task_id>/result", methods=["GET"])
    def api_task_result(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task["status"] != "success" or not task.get("result_ref"):
            return jsonify({
                "status": task["status"],
                "message": "Result not ready",
            }), 404
        result = tm.get_result(task_id)
        if result is None:
            return jsonify({"error": "Result unavailable"}), 404
        return jsonify({"task": task, "result": result})

    @app.route("/api/tasks/<task_id>/retry", methods=["POST"])
    def api_task_retry(task_id):
        tm = _get_task_manager()
        try:
            new_task = tm.retry(task_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        return jsonify(new_task)

    @app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
    def api_task_cancel(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task["status"] not in ("pending", "running"):
            return jsonify({
                "error": f"Cannot cancel task in status '{task['status']}'",
            }), 409
        ok = tm.cancel(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/<task_id>", methods=["DELETE"])
    def api_task_delete(task_id):
        tm = _get_task_manager()
        ok = tm.delete(task_id)
        if not ok:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"ok": True})

    @app.route("/api/tasks/stats", methods=["GET"])
    def api_task_stats():
        store = _get_task_store()
        return jsonify({
            "by_status": store.count_by_status(),
            "registered_types": _get_task_manager().registered_types(),
        })

    @app.route("/api/tasks/cleanup", methods=["POST"])
    def api_tasks_cleanup():
        """Manually trigger task + cache cleanup. Returns counts removed."""
        sched = _get_cleanup_scheduler()
        return jsonify(sched.run_once())

    # ── Diagnostics (Railway / cloud deployment) ────────────────────────

    @app.route("/api/diagnostics/providers", methods=["GET"])
    def api_diag_providers():
        """Quick reachability check for each enabled data provider.

        Designed to be called right after deploy to confirm the cloud
        environment can actually reach the configured data sources.
        Each probe has a hard 8-second timeout — failures don't block.
        """
        results = _probe_providers()
        ok = all(r.get("ok") for r in results.values())
        return jsonify({
            "ok": ok,
            "providers": results,
            "routing": _get_data_router().routing_summary(),
        }), (200 if ok else 207)  # 207 = Multi-Status (some failed)

    # ── Seed Data ───────────────────────────────────────────────────────

    @app.route("/api/seed", methods=["POST"])
    def api_seed():
        from stock_trading_system.web.seed_data import seed_msft_analysis
        seed_msft_analysis()
        return jsonify({"ok": True, "message": "MSFT mock data seeded"})

    # ── WebSocket Events ────────────────────────────────────────────────

    @socketio.on("connect")
    def handle_connect():
        logger.info("Client connected")

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("Client disconnected")

    return app


def run_app(host="0.0.0.0", port=5000, debug=False, config_path=None):
    """Create and run the web application.

    Honors the PORT environment variable (Railway / Heroku style platforms).
    """
    import os as _os
    env_port = _os.environ.get("PORT")
    if env_port:
        try:
            port = int(env_port)
        except ValueError:
            logger.warning("Invalid PORT env var %r — using %s", env_port, port)

    app = create_app(config_path)

    # Start background task/cache cleanup once the app is built. Safe to call
    # repeatedly; the scheduler is idempotent.
    try:
        _get_cleanup_scheduler().start()
    except Exception as e:  # noqa: BLE001 — never let cleanup break startup
        logger.warning("Cleanup scheduler failed to start: %s", e)

    logger.info("Starting web server on %s:%s", host, port)
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
