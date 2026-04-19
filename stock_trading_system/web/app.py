"""Flask web application with API routes and WebSocket support."""

import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from stock_trading_system.config import load_config, get_config, save_config
from stock_trading_system.config.settings import update_user_config, WRITABLE_SETTING_PATHS
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


def _mask_secret(value: str, keep: int = 4) -> str:
    """Mask a sensitive string, keeping only the last `keep` characters."""
    if not value:
        return ""
    s = str(value)
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def _reset_config_dependent_singletons(paths: list[str]):
    """Clear lazy singletons whose config might have changed.

    Called after a successful /api/settings POST so the next request picks
    up the new config. We only reset the ones we know about — the scheduler
    thread is left alone (user can restart it from the UI if needed).
    """
    global _analyzer, _alert_monitor, _data_manager, _screener, _strategy_engine, _report_gen
    paths = paths or []
    touched_gemini = any(p.startswith("gemini.") for p in paths)
    touched_qwen = any(p.startswith("qwen.") for p in paths)
    touched_polygon = any(p.startswith("polygon.") for p in paths)
    touched_ib = any(p.startswith("ib.") for p in paths)
    touched_alerts = any(p.startswith("alerts.") for p in paths)
    # Analyzer uses gemini config.
    if touched_gemini:
        _analyzer = None
    # Data manager fans out to IB/Polygon/Qwen.
    if touched_ib or touched_polygon or touched_qwen:
        _data_manager = None
        _screener = None
    # Alert monitor owns notifier handles + its own DataManager.
    if touched_alerts or touched_ib or touched_polygon or touched_qwen:
        _alert_monitor = None
    # Reports depend on config defaults for output dir.
    _report_gen = None
    _strategy_engine = None


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

    # ── Health Check ────────────────────────────────────────────────────
    # Lightweight probe used by Railway / Render / k8s liveness checks.
    # Intentionally avoids touching the DB, data sources, or any lazily
    # initialized singleton so it stays fast and never triggers network I/O.

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok", "service": "stock-trading-system"})

    # ── Dashboard API ───────────────────────────────────────────────────

    @app.route("/api/dashboard")
    def api_dashboard():
        pm = _get_portfolio_mgr()
        pnl = pm.get_pnl()
        holdings = pm.get_holdings()
        alerts = _get_alert_monitor().list_alerts()
        history = pm.get_history(days=30)
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
        pm.sell_position(
            ticker, float(data["shares"]), float(data["price"]),
            date=data.get("date"), notes=data.get("notes", ""),
        )
        return jsonify({"ok": True, "message": f"SELL {data['shares']} {ticker} @ {data['price']}"})

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

                def _progress(event: dict):
                    # Forward pipeline events verbatim, adding ticker for the UI
                    # to filter out stale updates if multiple runs overlap.
                    payload = {"ticker": ticker, **event}
                    socketio.emit("analysis_pipeline", payload)

                analyzer = _get_analyzer()
                result = analyzer.analyze(ticker, date, progress_cb=_progress)

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
                    "steps": result.steps,
                }
                socketio.emit("analysis_result", result_data)

                # Save to history
                try:
                    import json as _json
                    from stock_trading_system.portfolio.database import PortfolioDatabase
                    db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                    db = PortfolioDatabase(db_path)
                    # Record which LLM actually produced this run so the history
                    # page can show provenance for cross-model comparisons.
                    gemini_cfg = get_config().get("gemini", {}) or {}
                    model_name = gemini_cfg.get("deep_think_model") or gemini_cfg.get("model", "")
                    db.save_analysis({
                        **result_data,
                        "advice_json": _json.dumps(advice, ensure_ascii=False) if advice else "",
                        "steps_json": _json.dumps(result.steps, ensure_ascii=False),
                        "model": model_name,
                        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    logger.info("Analysis saved to history: %s", ticker)
                except Exception as save_err:
                    logger.warning("Failed to save analysis history: %s", save_err)
            except Exception as e:
                logger.error("Analysis failed for %s: %s", ticker, e)
                socketio.emit("analysis_error", {"ticker": ticker, "error": str(e)})

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

    # ── Analysis History API ──────────────────────────────────────────────

    @app.route("/api/history")
    def api_analysis_history():
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        ticker = request.args.get("ticker")
        records = db.get_analysis_history(ticker=ticker)
        return jsonify(records)

    @app.route("/api/history/<int:analysis_id>")
    def api_analysis_detail(analysis_id):
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        record = db.get_analysis_by_id(analysis_id)
        if record:
            return jsonify(record)
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/history/compare")
    def api_analysis_compare():
        """Compare multiple analyses side-by-side. Query: ?ids=1,2,3 (up to 5)."""
        from stock_trading_system.portfolio.database import PortfolioDatabase
        ids_raw = request.args.get("ids", "").strip()
        if not ids_raw:
            return jsonify({"error": "Missing ids"}), 400
        try:
            ids = [int(x) for x in ids_raw.split(",") if x.strip()]
        except ValueError:
            return jsonify({"error": "Invalid ids"}), 400
        if not ids:
            return jsonify({"error": "Missing ids"}), 400
        if len(ids) > 5:
            return jsonify({"error": "At most 5 records can be compared"}), 400
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        records = db.get_analyses_by_ids(ids)
        return jsonify({"count": len(records), "records": records})

    @app.route("/api/history/timeline/<ticker>")
    def api_analysis_timeline(ticker):
        """Structured chronological history for one ticker (drift view)."""
        from stock_trading_system.portfolio.database import PortfolioDatabase
        limit = int(request.args.get("limit", 20))
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        records = db.get_analysis_timeline(ticker.upper(), limit=limit)
        return jsonify({"ticker": ticker.upper(), "count": len(records), "records": records})

    @app.route("/api/history/<int:analysis_id>", methods=["DELETE"])
    def api_analysis_delete(analysis_id):
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        ok = db.delete_analysis(analysis_id)
        return jsonify({"ok": ok})

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
            "writable_paths": sorted(WRITABLE_SETTING_PATHS),
        })

    @app.route("/api/settings", methods=["POST"])
    def api_settings_update():
        """Write whitelisted settings to ~/.stock_trading/config.yaml.

        Body: { "gemini.api_key": "sk-...", "qwen.enabled": true, ... }
        Only keys listed in WRITABLE_SETTING_PATHS are accepted; unknown
        keys are silently ignored. Empty strings DO get persisted so the
        user can clear a bad credential.
        """
        data = request.json or {}
        if not isinstance(data, dict):
            return jsonify({"error": "Expected JSON object"}), 400
        # Reject empty writes outright — no point rewriting the file.
        valid_updates = {k: v for k, v in data.items() if k in WRITABLE_SETTING_PATHS}
        if not valid_updates:
            return jsonify({"error": "No writable fields provided"}), 400
        try:
            new_cfg = update_user_config(valid_updates)
        except Exception as e:
            logger.error("Failed to write user config: %s", e)
            return jsonify({"error": str(e)}), 500
        applied = new_cfg.get("_applied_paths", []) or []
        _reset_config_dependent_singletons(applied)
        logger.info("Settings updated: %s", applied)
        return jsonify({"ok": True, "applied": applied, "count": len(applied)})

    # ── Backtesting ─────────────────────────────────────────────────────

    @app.route("/api/backtest/strategies")
    def api_backtest_strategies():
        """List available backtest strategies with their parameter schemas."""
        from stock_trading_system.strategy.backtest import Backtester
        bt = Backtester(get_config())
        return jsonify({"strategies": bt.list_strategies()})

    @app.route("/api/backtest/run", methods=["POST"])
    def api_backtest_run():
        """Run a backtest and return the equity curve + trades + stats.

        Body: {
            "ticker": "AAPL",
            "strategy": "sma_crossover",
            "period": "1y",
            "initial_capital": 100000,
            "params": { "short_window": 20, "long_window": 50 }
        }
        """
        from dataclasses import asdict
        from stock_trading_system.strategy.backtest import Backtester
        data = request.json or {}
        ticker = (data.get("ticker") or "").upper().strip()
        strategy = data.get("strategy") or "buy_and_hold"
        period = data.get("period") or "1y"
        try:
            initial_capital = float(data.get("initial_capital") or 100_000)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid initial_capital"}), 400
        params = data.get("params") or {}
        if not ticker:
            return jsonify({"error": "Missing ticker"}), 400

        try:
            bt = Backtester(get_config())
            result = bt.run(
                ticker=ticker,
                strategy_id=strategy,
                initial_capital=initial_capital,
                period=period,
                params=params,
            )
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            logger.error("Backtest failed: %s", e)
            return jsonify({"error": str(e)}), 500

        # Convert dataclasses to dicts for JSON serialisation.
        payload = asdict(result)
        payload["trades"] = [asdict(t) if not isinstance(t, dict) else t for t in result.trades]
        return jsonify(payload)

    # ── Global Search ───────────────────────────────────────────────────

    @app.route("/api/search")
    def api_search():
        """Unified search across positions, transactions, alerts, analysis history.

        Query: ?q=<substring>&limit=<per-group>
        Returns: { q, positions, transactions, analyses, alerts } — each a list.
        Matching is case-insensitive substring against ticker plus
        category-specific fields (action/signal/condition/notes).
        """
        raw = (request.args.get("q") or "").strip()
        if not raw:
            return jsonify({
                "q": "", "positions": [], "transactions": [],
                "analyses": [], "alerts": [],
            })
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
        q = raw.lower()

        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)

        # Positions — read rows directly so we don't trigger live price fetches.
        positions_out = []
        try:
            for p in db.get_all_positions():
                if q in p.ticker.lower():
                    positions_out.append({
                        "ticker": p.ticker,
                        "market": p.market,
                        "shares": p.shares,
                        "avg_cost": p.avg_cost,
                        "added_date": p.added_date,
                    })
        except Exception as e:
            logger.warning("search positions failed: %s", e)
        positions_out = positions_out[:limit]

        # Transactions — ticker, action, notes.
        transactions_out = []
        try:
            for t in db.get_transactions():
                hay = f"{t.ticker} {t.action} {t.notes or ''}".lower()
                if q in hay:
                    transactions_out.append({
                        "id": t.id, "ticker": t.ticker, "action": t.action,
                        "shares": t.shares, "price": t.price,
                        "timestamp": t.timestamp, "notes": t.notes,
                    })
                if len(transactions_out) >= limit:
                    break
        except Exception as e:
            logger.warning("search transactions failed: %s", e)

        # Analysis history — ticker, signal, action. Keep payload small.
        analyses_out = []
        try:
            # Pull a reasonable window and filter in Python; avoids full-table scans
            # while still matching against the structured columns already stored.
            for r in db.get_analysis_history(limit=500):
                hay = " ".join(str(r.get(k) or "") for k in ("ticker", "signal", "action", "confidence", "model")).lower()
                if q in hay:
                    analyses_out.append({
                        "id": r.get("id"),
                        "ticker": r.get("ticker"),
                        "date": r.get("date"),
                        "signal": r.get("signal"),
                        "action": r.get("action"),
                        "confidence": r.get("confidence"),
                        "model": r.get("model"),
                        "created_at": r.get("created_at"),
                    })
                if len(analyses_out) >= limit:
                    break
        except Exception as e:
            logger.warning("search analyses failed: %s", e)

        # Alerts — match ticker or condition (e.g. "price_above").
        alerts_out = []
        try:
            for a in db.get_active_alerts():
                hay = f"{a.get('ticker','')} {a.get('condition','')}".lower()
                if q in hay:
                    alerts_out.append({
                        "id": a.get("id"),
                        "ticker": a.get("ticker"),
                        "condition": a.get("condition"),
                        "threshold": a.get("threshold"),
                        "created": a.get("created"),
                    })
                if len(alerts_out) >= limit:
                    break
        except Exception as e:
            logger.warning("search alerts failed: %s", e)

        return jsonify({
            "q": raw,
            "positions": positions_out,
            "transactions": transactions_out,
            "analyses": analyses_out,
            "alerts": alerts_out,
        })

    # ── LLM Provider Switch ──────────────────────────────────────────

    @app.route("/api/settings/llm-provider", methods=["GET"])
    def get_llm_provider():
        from stock_trading_system.llm.router import (
            get_active_provider, has_provider_key, is_provider_locked_by_env,
        )
        cfg = get_config()
        return jsonify({
            "active": get_active_provider(cfg),
            "has_qwen_key": has_provider_key(cfg, "qwen"),
            "has_gemini_key": has_provider_key(cfg, "gemini"),
            "locked_by_env": is_provider_locked_by_env(),
        })

    @app.route("/api/settings/llm-provider", methods=["POST"])
    def set_llm_provider():
        from stock_trading_system.llm.router import is_provider_locked_by_env, has_provider_key
        from stock_trading_system.llm.constants import VALID_PROVIDERS
        if is_provider_locked_by_env():
            return jsonify({"reason": "locked_by_env", "message": "LLM_PROVIDER 已由环境变量锁定"}), 409
        body = request.get_json(silent=True) or {}
        provider = (body.get("provider") or "").strip().lower()
        if provider not in VALID_PROVIDERS:
            return jsonify({"reason": "invalid_provider", "message": f"provider 必须是 {sorted(VALID_PROVIDERS)} 之一"}), 400
        cfg = get_config()
        if not has_provider_key(cfg, provider):
            label = "Qwen" if provider == "qwen" else "Gemini"
            return jsonify({"reason": "missing_api_key", "message": f"{label} 未配置 API key"}), 400
        save_config({"llm_provider": provider})
        return jsonify({"active": provider, "source": "user_config"})

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
    """Create and run the web application."""
    app = create_app(config_path)
    logger.info("Starting web server on %s:%s", host, port)
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
