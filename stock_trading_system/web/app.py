"""Flask web application with API routes and WebSocket support."""

import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from stock_trading_system.config import load_config, get_config
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
                analyzer = _get_analyzer()
                result = analyzer.analyze(ticker, date)

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
                try:
                    import json as _json
                    from stock_trading_system.portfolio.database import PortfolioDatabase
                    db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                    db = PortfolioDatabase(db_path)
                    db.save_analysis({
                        **result_data,
                        "advice_json": _json.dumps(advice, ensure_ascii=False) if advice else "",
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
