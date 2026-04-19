"""Flask web application with API routes and WebSocket support."""

import os
import threading
from pathlib import Path

from flask import Flask, render_template, jsonify, request, redirect, g
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
_paper_store = None
_task_store = None
_task_manager = None
_local_cache = None
_data_router = None
_cleanup_scheduler = None


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


def _get_paper_store():
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
    """Register worker functions for all known task types."""
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


def _get_data_router():
    """Lazy singleton DataRouter (Qwen-first with LocalCache)."""
    global _data_router
    if _data_router is None:
        from stock_trading_system.data.data_router import DataRouter
        _data_router = DataRouter(get_config(), cache=_get_local_cache())
    return _data_router


def _get_cleanup_scheduler():
    """Lazy singleton task+cache cleanup scheduler."""
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
    """Quick reachability check for each enabled provider."""
    import time as _time
    cfg = get_config()
    providers = cfg.get("providers", {}) or {}
    results: dict = {}

    def _probe(name, fn):
        start = _time.perf_counter()
        try:
            ok = bool(fn())
            return {"ok": ok,
                    "latency_ms": int((_time.perf_counter() - start) * 1000),
                    "error": None if ok else "no data"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False,
                    "latency_ms": int((_time.perf_counter() - start) * 1000),
                    "error": str(e)[:200]}

    try:
        router = _get_data_router()
        if router.qwen.enabled:
            results["qwen"] = _probe("qwen", lambda: router.qwen.get_stock_price("AAPL"))
    except Exception:
        pass

    if providers.get("yfinance_enabled", True):
        try:
            from stock_trading_system.data.yfinance_provider import YFinanceProvider
            yf = YFinanceProvider()
            results["yfinance"] = _probe("yfinance", lambda: yf.get_stock_price("AAPL"))
        except Exception as e:
            results["yfinance"] = {"ok": False, "error": str(e)[:200]}

    if providers.get("akshare_enabled", True):
        try:
            from stock_trading_system.data.akshare_provider import AkShareProvider
            ak = AkShareProvider()
            results["akshare"] = _probe("akshare", lambda: ak.get_stock_price("600519"))
        except Exception as e:
            results["akshare"] = {"ok": False, "error": str(e)[:200]}

    if providers.get("polygon_enabled", False):
        try:
            from stock_trading_system.data.polygon_provider import PolygonProvider
            pg = PolygonProvider(cfg)
            results["polygon"] = _probe("polygon", lambda: pg.get_stock_price("AAPL"))
        except Exception as e:
            results["polygon"] = {"ok": False, "error": str(e)[:200]}

    if providers.get("ib_enabled", False):
        ib_cfg = cfg.get("ib", {}) or {}
        results["ib"] = {
            "ok": False, "latency_ms": 0,
            "error": "IB requires local TWS; not testable from a cloud probe.",
            "host": ib_cfg.get("host"), "port": ib_cfg.get("port"),
        }
    return results


def _resolve_secret_key() -> str:
    """Resolve Flask SECRET_KEY: env > file > auto-generate.

    Priority:
        1. FLASK_SECRET_KEY env var
        2. ~/.stock_trading/flask_secret.key file
        3. Auto-generate + persist to file (first-run)
    """
    env_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if env_key:
        return env_key

    key_path = Path.home() / ".stock_trading" / "flask_secret.key"
    if key_path.exists():
        stored = key_path.read_text().strip()
        if stored:
            return stored

    # Auto-generate on first run
    import secrets
    new_key = secrets.token_hex(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(new_key)
    key_path.chmod(0o600)
    logger.info(
        "Generated Flask SECRET_KEY → %s (chmod 600). "
        "Back this up or set FLASK_SECRET_KEY env var.",
        key_path,
    )
    return new_key


def create_app(config_path=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = _resolve_secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not app.debug

    from datetime import timedelta
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    load_config(config_path)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # ── Auth setup ─────────────────────────────────────────────────────

    cfg = get_config()
    db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")

    from stock_trading_system.auth.repository import UserRepository
    from stock_trading_system.auth.session import load_current_user, login_user, logout_user
    from stock_trading_system.auth.password import verify_password, validate_password_strength
    from stock_trading_system.auth.invite import InviteCodeManager
    from stock_trading_system.auth.bootstrap import ensure_multi_tenant_ready

    _user_repo = UserRepository(db_path)
    _invite_mgr = InviteCodeManager(db_path)
    _multi_tenant_ready = ensure_multi_tenant_ready(db_path)

    # Public paths that don't require authentication
    PUBLIC_PREFIXES = ("/static/", "/login", "/register", "/reset",
                       "/api/auth/login", "/api/auth/register", "/api/auth/reset",
                       "/health", "/api/health", "/api/seed")

    @app.before_request
    def enforce_auth():
        """Load current user and enforce authentication."""
        if _multi_tenant_ready:
            load_current_user(_user_repo)
        else:
            # Single-user fallback: no users table yet
            from flask import g
            g.user = None
            return  # allow all access in non-migrated mode

        from flask import g
        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return
        if g.user is None:
            if path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login?next=" + path)

    # ── Auth API Routes ────────────────────────────────────────────────

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/register")
    def register_page():
        return render_template("register.html")

    @app.route("/api/auth/login", methods=["POST"])
    def api_login():
        body = request.get_json(silent=True) or {}
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        if not email or not password:
            return jsonify({"error": "invalid_credentials", "message": "请输入邮箱和密码"}), 401

        user = _user_repo.find_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            return jsonify({"error": "invalid_credentials", "message": "邮箱或密码错误"}), 401

        login_user(user.id)
        _user_repo.update_last_login(user.id)
        return jsonify({"user": {"id": user.id, "email": user.email,
                                  "display_name": user.display_name, "role": user.role}})

    @app.route("/api/auth/register", methods=["POST"])
    def api_register():
        body = request.get_json(silent=True) or {}
        invite_code = body.get("invite_code") or ""
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        display_name = body.get("display_name")

        # Validate invite code
        err = _invite_mgr.validate(invite_code)
        if err:
            return jsonify({"error": err, "message": f"邀请码无效: {err}"}), 400

        # Validate email
        if not email or "@" not in email:
            return jsonify({"error": "invalid_email", "message": "请输入有效邮箱"}), 400
        if _user_repo.find_by_email(email):
            return jsonify({"error": "email_taken", "message": "该邮箱已注册"}), 400

        # Validate password
        pwd_err = validate_password_strength(password)
        if pwd_err:
            return jsonify({"error": "password_weak", "message": pwd_err}), 400

        # Create user + redeem invite
        user = _user_repo.create(email, password, display_name)
        _invite_mgr.redeem(invite_code, user.id)
        login_user(user.id)

        return jsonify({"user": {"id": user.id, "email": user.email,
                                  "display_name": user.display_name, "role": user.role}})

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():
        logout_user()
        return jsonify({"ok": True})

    @app.route("/api/auth/me")
    def api_auth_me():
        from flask import g
        u = g.get("user")
        if u is None:
            return jsonify({"user": None})
        return jsonify({"user": {"id": u.id, "email": u.email,
                                  "display_name": u.display_name, "role": u.role}})

    @app.route("/api/auth/change-password", methods=["POST"])
    def api_change_password():
        from flask import g
        u = g.get("user")
        if u is None:
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        old = body.get("old_password") or ""
        new = body.get("new_password") or ""
        if not verify_password(old, u.password_hash):
            return jsonify({"error": "wrong_password", "message": "当前密码错误"}), 401
        pwd_err = validate_password_strength(new)
        if pwd_err:
            return jsonify({"error": "password_weak", "message": pwd_err}), 400
        _user_repo.update_password(u.id, new)
        return jsonify({"ok": True})

    # ── Admin Routes ───────────────────────────────────────────────────

    from stock_trading_system.auth.decorators import admin_required

    @app.route("/api/admin/invites", methods=["GET"])
    @admin_required
    def api_admin_invites_list():
        return jsonify({"invites": _invite_mgr.list_all()})

    @app.route("/api/admin/invites", methods=["POST"])
    @admin_required
    def api_admin_invites_create():
        from flask import g
        body = request.get_json(silent=True) or {}
        days = int(body.get("expires_in_days", 7))
        code = _invite_mgr.generate(g.user.id, expires_in_days=days)
        return jsonify({"code": code})

    @app.route("/api/admin/invites/<code>", methods=["DELETE"])
    @admin_required
    def api_admin_invites_revoke(code):
        ok = _invite_mgr.revoke(code)
        return jsonify({"ok": ok})

    @app.route("/api/admin/users")
    @admin_required
    def api_admin_users():
        users = _user_repo.list_all()
        return jsonify({"users": [
            {"id": u.id, "email": u.email, "display_name": u.display_name,
             "role": u.role, "status": u.status, "created_at": u.created_at,
             "last_login_at": u.last_login_at}
            for u in users
        ]})

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

    # ── Screen V2 (async task-based) ────────────────────────────────────

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
        store = _get_task_store()
        result = store.get_screen_v2_result(result_id)
        if not result:
            return jsonify({"error": "Not found"}), 404
        return jsonify(result)

    @app.route("/api/screen/v2/result/by_task/<task_id>")
    def api_screen_v2_result_by_task(task_id: str):
        store = _get_task_store()
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
        limit = int(request.args.get("limit", 50))
        store = _get_task_store()
        return jsonify(store.list_screen_v2_history(limit=limit))

    @app.route("/api/screen/v2/gurus")
    def api_screen_v2_gurus():
        from stock_trading_system.screener.v2 import all_guru_metadata
        return jsonify(all_guru_metadata())

    # ── Paper Trade API ─────────────────────────────────────────────────

    @app.route("/api/paper/sessions", methods=["POST"])
    def api_paper_create_session():
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
        data = request.json or {}
        analysis_id = data.get("analysis_id")
        session_id = data.get("session_id")
        if not analysis_id or not session_id:
            return jsonify({"ok": False, "error": "analysis_id + session_id required"}), 400
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
        store = _get_paper_store()
        from stock_trading_system.strategy.paper_trader import ticker_summary
        return jsonify(ticker_summary(store, ticker))

    @app.route("/api/paper/tickers")
    def api_paper_tickers():
        store = _get_paper_store()
        sessions = store.list_ticker_sessions()
        out = []
        for s in sessions:
            sid = int(s["id"])
            last = store.last_daily_stat(sid)
            latest_evt = store.latest_strategy_event(sid)
            events = store.list_strategy_events(sid)
            dailies = store.list_daily_stats(sid, limit=1000)
            spark = [float(d["total_value"]) for d in dailies[-30:]]
            buys = [e for e in events
                    if (e.get("new_signal") or "").upper() in ("BUY", "OVERWEIGHT")]
            hits, total = 0, 0
            for e in buys:
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
        active_orders = []
        if active_plan:
            active_orders = store.list_orders(plan_id=active_plan["id"])
        plan_history = []
        from stock_trading_system.portfolio.database import PortfolioDatabase as _PDB
        _db = _PDB(get_config().get("portfolio", {}).get("db_path", "data/portfolio.db"))
        for p in all_plans:
            p_orders = store.list_orders(plan_id=p["id"])
            entry = {**p, "orders": p_orders}
            # Attach trade_decision text from the linked analysis
            if p.get("analysis_id"):
                try:
                    _ana = _db.get_analysis_by_id(p["analysis_id"])
                    entry["trade_decision"] = (_ana or {}).get("trade_decision") or ""
                except Exception:
                    entry["trade_decision"] = ""
            plan_history.append(entry)
        latest = events[0] if events else None
        latest_advice = None
        latest_trade_decision = None
        if latest:
            try:
                from stock_trading_system.portfolio.database import PortfolioDatabase
                db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
                ana = PortfolioDatabase(db_path).get_analysis_by_id(latest["analysis_id"])
                if ana:
                    latest_trade_decision = ana.get("trade_decision") or ""
                    if ana.get("advice_json"):
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
            "latest_trade_decision": latest_trade_decision,
            "active_plan": active_plan,
            "active_orders": active_orders,
            "plan_history": plan_history,
        })

    @app.route("/api/paper/tickers/<ticker>/eod", methods=["POST"])
    def api_paper_ticker_eod(ticker: str):
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
        try:
            tm = _get_task_manager()
            task = tm.submit("paper_backfill", {})
            return jsonify({"ok": True, "task_id": task["id"], "task": task})
        except Exception as e:
            logger.error("Backfill submit failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── Tasks API ───────────────────────────────────────────────────────

    @app.route("/api/tasks/submit", methods=["POST"])
    def api_task_submit():
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
            return jsonify({"status": task["status"], "message": "Result not ready"}), 404
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
            return jsonify({"error": f"Cannot cancel task in status '{task['status']}'"}), 409
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
        sched = _get_cleanup_scheduler()
        return jsonify(sched.run_once())

    # ── Diagnostics ─────────────────────────────────────────────────────

    @app.route("/api/diagnostics/providers", methods=["GET"])
    def api_diag_providers():
        """Quick reachability check for each enabled data provider."""
        results = _probe_providers()
        ok = all(r.get("ok") for r in results.values())
        try:
            routing = _get_data_router().routing_summary()
        except Exception:
            routing = {}
        return jsonify({
            "ok": ok,
            "providers": results,
            "routing": routing,
        }), (200 if ok else 207)

    # ── Iteration / Agent Evolution ─────────────────────────────────────

    @app.route("/api/iteration/agents", methods=["GET"])
    def api_iteration_agents():
        try:
            from stock_trading_system.agents.iterative.config import load_iteration_config
            from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
            cfg = get_config()
            iter_config = load_iteration_config(cfg.get("iteration", {}))
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            scorer = AgentScorer(db_path, iter_config)
            metrics = scorer.get_all_agent_metrics()
            weights = scorer.get_all_weights()
            agents = []
            for agent_id in metrics:
                agents.append({
                    "agent_id": agent_id,
                    "sharpe": metrics[agent_id]["sharpe"],
                    "hit_rate": metrics[agent_id]["hit_rate"],
                    "weight": weights.get(agent_id, 1.0),
                })
            agents.sort(key=lambda a: a["sharpe"], reverse=True)
            return jsonify({
                "enabled": iter_config.enabled,
                "agents": agents,
            })
        except Exception as e:
            logger.error("Failed to load iteration agents: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/iteration/meta/run", methods=["POST"])
    def api_iteration_meta_run():
        try:
            from stock_trading_system.agents.iterative.config import load_iteration_config
            from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
            from stock_trading_system.agents.iterative.prompt_store import PromptStore
            from stock_trading_system.agents.iterative.meta_agent import MetaAgent
            cfg = get_config()
            iter_config = load_iteration_config(cfg.get("iteration", {}))
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            scorer = AgentScorer(db_path, iter_config)
            prompt_store = PromptStore(db_path)
            session_store = None
            try:
                from stock_trading_system.strategy.paper_trader.session_store import SessionStore
                session_store = SessionStore(db_path)
            except Exception:
                pass
            meta = MetaAgent(
                scorer=scorer, prompt_store=prompt_store,
                config=iter_config, session_store=session_store,
            )
            data = request.get_json(silent=True) or {}
            action = data.get("action", "mutate")
            if action == "settle":
                results = meta.settle_ab_tests()
                return jsonify({"action": "settle", "results": results})
            result = meta.run_weekly()
            return jsonify(result)
        except Exception as e:
            logger.error("Meta agent run failed: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.route("/api/iteration/prompts", methods=["GET"])
    def api_iteration_prompts():
        try:
            from stock_trading_system.agents.iterative.prompt_store import PromptStore
            cfg = get_config()
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            store = PromptStore(db_path)
            agent_id = request.args.get("agent_id")
            history = store.get_history(agent_id=agent_id, limit=50)
            return jsonify({"prompts": history})
        except Exception as e:
            logger.error("Failed to load prompt history: %s", e)
            return jsonify({"error": str(e)}), 500

    # ── Screener V3 API ──────────────────────────────────────────────

    @app.route("/api/screen/v3/gurus")
    def api_screen_v3_gurus():
        """Return metadata for all 14 guru agents (config panel)."""
        from stock_trading_system.screener.v3.pipeline import get_all_guru_metas
        return jsonify({"gurus": get_all_guru_metas()})

    @app.route("/api/screen/v3/estimate", methods=["POST"])
    def api_screen_v3_estimate():
        """Estimate cost and duration for a V3 screening run."""
        from stock_trading_system.screener.v3.estimator import estimate
        from stock_trading_system.llm.router import get_active_provider
        from flask import g

        body = request.get_json(silent=True) or {}
        cfg = get_config()
        user_id = getattr(g, "user", None) and g.user.id
        provider = get_active_provider(cfg, user_id=user_id)

        result = estimate(
            num_candidates=int(body.get("candidate_n", 20)),
            num_gurus=len(body.get("gurus", ["buffett", "graham", "munger", "lynch"])),
            with_roundtable=bool(body.get("with_roundtable", False)),
            provider=provider,
        )
        return jsonify(result)

    @app.route("/api/screen/v3/trigger", methods=["POST"])
    def api_screen_v3_trigger():
        """Trigger a V3 screening task."""
        from flask import g
        from stock_trading_system.llm.router import get_active_provider

        body = request.get_json(silent=True) or {}
        cfg = get_config()
        user_id = getattr(g, "user", None) and g.user.id
        provider = get_active_provider(cfg, user_id=user_id)

        params = {
            "nl_query": body.get("nl_query", ""),
            "market": body.get("market", "us"),
            "candidate_n": int(body.get("candidate_n", 20)),
            "gurus": body.get("gurus", ["buffett", "graham", "munger", "lynch"]),
            "mode": body.get("mode", "agent"),
            "with_roundtable": bool(body.get("with_roundtable", False)),
            "user_id": user_id,
            "provider": provider,
        }

        tm = _get_task_manager()
        task = tm.submit(
            task_type="screen_v3",
            params=params,
            title=f"V3 选股: {params['nl_query'][:30] or '默认'}",
        )
        return jsonify({"task_id": task["id"], "estimated": params})

    @app.route("/api/screen/v3/results/<result_id>")
    def api_screen_v3_result(result_id):
        """Return full V3 screening result."""
        try:
            from stock_trading_system.screener.v2.result_store import ScreenResultStore
            store = ScreenResultStore(
                get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
            )
            result = store.get_by_id(int(result_id))
            if not result:
                return jsonify({"error": "not found"}), 404
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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
