"""Flask web application with API routes and WebSocket support."""

import json
import os
import threading
from pathlib import Path

from flask import Flask, render_template, jsonify, request, redirect, g, Response
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
        _portfolio_mgr = PortfolioManager(get_config(), data_manager=_get_data_manager())
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
        _data_manager = DataManager(get_config(), cache=_get_local_cache())
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


def _rendering_available_tabs(raw) -> list[str]:
    """Tab keys that are populated in ``rendering_json``. v1.7 helper —
    surfaces a structural list the frontend uses for "已生成结构化卡片
    N/8" hints, without re-parsing the cards themselves."""
    if not raw:
        return []
    try:
        from stock_trading_system.agents.rendering.status import available_tabs
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return available_tabs(parsed) if isinstance(parsed, dict) else []
    except (json.JSONDecodeError, TypeError, ImportError):
        return []


def _infer_rendering_status_legacy(record: dict) -> str:
    """v1.7 — fallback for rows that predate the status state machine
    (``rendering_status`` column NULL because the row was written
    before this release migrated). We compute the status on the fly
    from ``rendering_json``: empty → ``empty``, otherwise re-classify.
    Once the row has been re-saved by the worker / backfill the
    persisted column wins."""
    raw = record.get("rendering_json")
    if not raw:
        return "empty"
    try:
        from stock_trading_system.agents.rendering.status import classify
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return "empty"
        status, _ = classify(parsed)
        return status
    except (json.JSONDecodeError, TypeError, ImportError):
        return "empty"


def _parse_rendering(raw) -> dict:
    """Best-effort decode + DTO normalize of ``analysis_history.rendering_json``.

    Returns the parsed dict on success; an empty dict for missing /
    malformed rows. NEVER returns the raw string — the API contract
    promises a structured object so clients can read ``rendering[tab]``
    without re-parsing.

    v1.21: every tab card is also passed through ``_normalize_card`` so a
    single bad enum / non-list field can no longer take down the React
    detail page (the production /analysis/17 white-screen). Cards that
    can't be normalised at all are dropped — the frontend falls back to
    the markdown body for those tabs.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        parsed = raw
    else:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict = {}
    for tab_key, card in parsed.items():
        normalised = _normalize_card(tab_key, card)
        if normalised is not None:
            out[tab_key] = normalised
    return out


# Per-card normalisers. Each returns either a sanitised dict or None
# (drop the card entirely so the frontend ErrorBoundary fallback kicks in
# AND the markdown body still renders the same content as plain text).

def _normalize_card(tab_key: str, card) -> dict | None:
    """Project a single tab card into a defensive shape.

    Contract:
        * Drops the card entirely when ``card`` isn't a dict.
        * Coerces array fields to ``[]`` when missing / non-list.
        * Coerces missing object fields to ``None`` (frontend renders
          empty state) instead of leaving them undefined.
        * Coerces non-numeric "number" fields to ``None`` so the card
          can render "—" instead of crashing on ``.toFixed``.
    """
    if not isinstance(card, dict):
        return None

    # Generic per-tab massage. Tabs we don't know about pass through
    # unchanged but still get list/dict guards on common keys.
    out = dict(card)

    # 1. Overview ----------------------------------------------------
    if tab_key == "summary":
        out["key_metrics"] = _ensure_list(out.get("key_metrics"))
        out["decision_drivers"] = _ensure_list(out.get("decision_drivers"))
        ds = out.get("debate_synthesis")
        out["debate_synthesis"] = ds if isinstance(ds, dict) else None

    # 2. Market ------------------------------------------------------
    elif tab_key == "Market":
        out["indicators"] = _ensure_list(out.get("indicators"))
        out["support_resistance"] = [
            {**lvl, "price": _coerce_finite(lvl.get("price"))}
            for lvl in _ensure_list(out.get("support_resistance"))
            if isinstance(lvl, dict)
        ]
        out["patterns"] = [p for p in _ensure_list(out.get("patterns"))
                            if isinstance(p, str) and p.strip()]

    # 3. Sentiment ---------------------------------------------------
    elif tab_key == "Sentiment":
        out["drivers"] = _ensure_list(out.get("drivers"))
        out["mood_score"] = _coerce_finite(out.get("mood_score")) or 0

    # 4. News --------------------------------------------------------
    elif tab_key == "News":
        out["headlines"] = _ensure_list(out.get("headlines"))
        out["catalysts"] = _ensure_list(out.get("catalysts"))

    # 5. Fundamentals -----------------------------------------------
    elif tab_key == "Fundamentals":
        for sub in ("valuation", "growth", "profitability", "balance_sheet"):
            v = out.get(sub)
            out[sub] = v if isinstance(v, dict) else None
        qs = _coerce_finite(out.get("quality_score"))
        out["quality_score"] = qs if qs is not None else None

    # 6. Investment Debate ------------------------------------------
    elif tab_key == "Investment Debate":
        out["bull_arguments"] = _ensure_list(out.get("bull_arguments"))
        out["bear_arguments"] = _ensure_list(out.get("bear_arguments"))

    # 7. Risk Assessment --------------------------------------------
    elif tab_key == "Risk Assessment":
        out["top_risks"] = _ensure_list(out.get("top_risks"))
        for stance_key in ("aggressive", "conservative", "neutral"):
            v = out.get(stance_key)
            out[stance_key] = v if isinstance(v, dict) else None

    # 8. Decision ---------------------------------------------------
    elif tab_key == "Decision":
        ez = out.get("entry_zone")
        out["entry_zone"] = ez if isinstance(ez, dict) else None
        out["structural_stop"] = _coerce_finite(out.get("structural_stop"))
        out["take_profit_levels"] = _ensure_list(out.get("take_profit_levels"))
        out["preconditions"] = [p for p in _ensure_list(out.get("preconditions"))
                                  if isinstance(p, str) and p.strip()]
        out["exit_conditions"] = [p for p in _ensure_list(out.get("exit_conditions"))
                                    if isinstance(p, str) and p.strip()]
        out["alternative_scenarios"] = _ensure_list(out.get("alternative_scenarios"))

    return out


def _ensure_list(v) -> list:
    """Always return a list. Non-list inputs degrade to ``[]`` so the
    frontend ``Array.isArray`` guard never has to hit a fallback."""
    return v if isinstance(v, list) else []


def _coerce_finite(v):
    """Coerce a value to a finite float or ``None``. Mirrors the
    ``toFiniteNumber`` helper on the frontend so both layers agree."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):  # bool is a subclass of int — exclude.
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    import math
    return n if math.isfinite(n) else None


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

    v1.0.1 (P1-C): added ``openrouter.`` prefix recognition. Pre-fix, a
    user changing OR api_key / base_url / headers / timeout / preset
    via /api/settings POST would NOT bust the analyzer cache; the next
    analysis kept using the stale config until manual provider switch
    or process restart.
    """
    global _analyzer, _alert_monitor, _data_manager, _screener, _strategy_engine, _report_gen
    paths = paths or []
    touched_gemini = any(p.startswith("gemini.") for p in paths)
    touched_qwen = any(p.startswith("qwen.") for p in paths)
    touched_openrouter = any(p.startswith("openrouter.") for p in paths)
    touched_polygon = any(p.startswith("polygon.") for p in paths)
    touched_ib = any(p.startswith("ib.") for p in paths)
    touched_alerts = any(p.startswith("alerts.") for p in paths)
    touched_llm = any(p.startswith("llm") for p in paths)
    # Analyzer uses LLM provider config — qwen / gemini / openrouter
    # all need to bust the cached analyzer + its TradingAgents graphs.
    if touched_gemini or touched_qwen or touched_openrouter or touched_llm:
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

    if providers.get("schwab_enabled", True):
        try:
            from stock_trading_system.data.schwab_provider import SchwabProvider
            sch = SchwabProvider(cfg)
            if sch.enabled:
                results["schwab"] = _probe(
                    "schwab", lambda: sch.get_stock_price("AAPL"),
                )
                results["schwab"]["token_age_days"] = sch.token_age_days()
            else:
                results["schwab"] = {
                    "ok": False, "latency_ms": 0,
                    "error": "schwab not configured "
                             "(missing token / app_key / disabled)",
                    "token_age_days": sch.token_age_days(),
                }
        except Exception as e:  # noqa: BLE001
            results["schwab"] = {"ok": False, "error": str(e)[:200]}

    # ── OpenRouter (v1.0 — llm-openrouter) ─────────────────────────
    # OR is technically an LLM aggregator, not a market-data provider,
    # but the diagnostics dashboard already aggregates "everything that
    # could fail at runtime" so we surface it here too. The probe is a
    # cheap HEAD against /api/v1/models — that endpoint requires the
    # api key and ~50ms round-trip; failure indicates either missing
    # key or network egress problem.
    from stock_trading_system.llm.router import has_provider_key as _has_or_key
    if _has_or_key(cfg, "openrouter"):
        import time as _t
        import requests as _rq
        or_cfg = cfg.get("openrouter") or {}
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or or_cfg.get("api_key", "")
        )
        base_url = or_cfg.get("base_url", "https://openrouter.ai/api/v1")
        start = _t.perf_counter()
        try:
            r = _rq.head(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            ok = 200 <= r.status_code < 400
            results["openrouter"] = {
                "ok":         ok,
                "latency_ms": int((_t.perf_counter() - start) * 1000),
                "status":     r.status_code,
                "error":      None if ok else f"HTTP {r.status_code}",
                "has_key":    True,
            }
        except Exception as e:  # noqa: BLE001
            results["openrouter"] = {
                "ok":         False,
                "latency_ms": int((_t.perf_counter() - start) * 1000),
                "error":      str(e)[:200],
                "has_key":    True,
            }
    else:
        # Surface as a known-disabled item (rather than absent) so the
        # diagnostics page can show "OR not configured" alongside the
        # other providers.
        results["openrouter"] = {
            "ok": False, "latency_ms": 0,
            "error": "openrouter not configured (no api_key in env or yaml)",
            "has_key": False,
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

    from stock_trading_system.tasks.event_emitter import ensure_task_events_table
    ensure_task_events_table(db_path)

    # ── Daily-snapshot scheduler ───────────────────────────────────────
    # Auto-starts once per deployment (worker-0 / single-process wins the
    # filesystem lock; the rest stay inert). Runs at 16:30 America/New_York
    # right after the US close. Disable with DISABLE_DAILY_SNAPSHOT_SCHEDULER=1
    # for tests / dev shells that don't want a background thread.
    if _multi_tenant_ready and not os.environ.get(
        "DISABLE_DAILY_SNAPSHOT_SCHEDULER"
    ):
        try:
            from stock_trading_system.scheduler.daily_snapshot_scheduler import (
                DailySnapshotScheduler, take_snapshot_all_users,
            )
        except ImportError as e:
            # APScheduler is optional. The web app must still boot when
            # it isn't installed (e.g. minimal CI image / lightweight
            # tests) — we just skip the daily-snapshot job and log loudly
            # so an operator running prod without the dep notices.
            logger.warning(
                "Daily-snapshot scheduler disabled (missing dep: %s). "
                "Snapshots will only run via the manual CLI/cron path.",
                e,
            )
        else:
            def _snapshot_all_users():
                return take_snapshot_all_users(
                    _user_repo,
                    portfolio_manager_factory=lambda _uid: _get_portfolio_mgr(),
                )

            DailySnapshotScheduler.reset()
            scheduler = DailySnapshotScheduler.get(_snapshot_all_users)
            scheduler.start_if_primary()

    # Public paths that don't require authentication
    PUBLIC_PREFIXES = ("/static/", "/login", "/register", "/reset",
                       "/api/auth/login", "/api/auth/register", "/api/auth/reset",
                       "/api/auth/invites-available",
                       "/health", "/api/health", "/api/seed",
                       # Schwab OAuth — guarded by magic-link secret instead of session
                       "/oauth/schwab/", "/api/schwab/")

    @app.before_request
    def enforce_auth():
        """Load current user and enforce authentication."""
        if _multi_tenant_ready:
            load_current_user(_user_repo)
        else:
            # Uninitialized: only allow public paths + migration trigger
            from flask import g
            g.user = None
            path = request.path
            if any(path.startswith(p) for p in PUBLIC_PREFIXES):
                return
            if path.startswith("/api/"):
                return jsonify({"error": "not_initialized",
                                "message": "System not initialized. Run multi-tenant migration."}), 503
            return redirect("/login")

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

    @app.route("/api/auth/invites-available")
    def api_invites_available():
        """Public check: are invite codes available for registration?"""
        codes = _invite_mgr.list_available(limit=1)
        return jsonify({"available": len(codes) > 0, "count": len(_invite_mgr.list_available(limit=100))})

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

    from stock_trading_system.web.vite_helpers import vite_assets

    @app.route("/")
    @app.route("/dashboard")
    def index():
        return render_template("islands/dashboard.html", vite_assets=vite_assets)

    @app.route("/app")
    def legacy_spa():
        """Legacy SPA fallback — all un-migrated pages live here."""
        return render_template("index.html")

    # ── React Island Routes ────────────────────────────────────────────

    @app.route("/screener-v3")
    def screener_v3_page():
        return render_template("islands/screener_v3.html", vite_assets=vite_assets)

    @app.route("/screener-v3/history")
    def screener_v3_history_page():
        # Reuse the same island bundle — the React entry inspects
        # ``window.location.pathname`` and dispatches to
        # ``<ScreenerHistoryList>``. This avoids a second Vite entry
        # for what is effectively a sibling view of the same app.
        return render_template("islands/screener_v3.html", vite_assets=vite_assets)

    @app.route("/paper-trade")
    def paper_trade_list_page():
        return render_template("islands/paper_trade_list.html", vite_assets=vite_assets)

    @app.route("/paper-trade/<ticker>")
    def paper_trade_detail_page(ticker):
        return render_template("islands/paper_trade_detail.html", vite_assets=vite_assets, ticker=ticker)

    @app.route("/tasks")
    @app.route("/tasks/<task_id>")
    def tasks_page_react(task_id=None):
        return render_template("islands/tasks.html", vite_assets=vite_assets)

    # Legacy URL redirects
    @app.route("/dashboard-v2")
    def dashboard_v2_redirect():
        return redirect("/")

    @app.route("/tasks-v2")
    @app.route("/tasks-v2/<task_id>")
    def tasks_v2_redirect(task_id=None):
        return redirect(f"/tasks/{task_id}" if task_id else "/tasks")

    @app.route("/portfolio")
    def portfolio_page():
        return render_template("islands/portfolio.html", vite_assets=vite_assets)

    @app.route("/history")
    def history_page():
        """v1.22: ``/analysis`` is now the unified inbox (running tasks +
        completed analyses + form). Bookmarked /history URLs keep working
        via 301 — preserving the query string so ``/history?ticker=AAPL``
        round-trips into ``/analysis?ticker=AAPL``."""
        qs = request.query_string.decode() if request.query_string else ""
        target = "/analysis" + (f"?{qs}" if qs else "")
        return redirect(target, code=301)

    @app.route("/alerts")
    def alerts_page():
        return render_template("islands/alerts.html", vite_assets=vite_assets)

    @app.route("/analysis")
    @app.route("/analysis/<analysis_id>")
    def analysis_page(analysis_id=None):
        return render_template("islands/analysis.html", vite_assets=vite_assets)

    @app.route("/backtest")
    @app.route("/backtest-v2")
    @app.route("/backtest/<backtest_id>")
    @app.route("/backtest-v2/<int:backtest_id>")
    def backtest_page(backtest_id=None):
        return render_template("islands/backtest.html", vite_assets=vite_assets)

    @app.route("/reports")
    def reports_page():
        return render_template("islands/reports.html", vite_assets=vite_assets)

    @app.route("/settings")
    @app.route("/settings/<section>")
    def settings_page(section=None):
        return render_template("islands/settings.html", vite_assets=vite_assets)

    # ── Health Check ────────────────────────────────────────────────────
    # Lightweight probe used by Railway / Render / k8s liveness checks.
    # Intentionally avoids touching the DB, data sources, or any lazily
    # initialized singleton so it stays fast and never triggers network I/O.

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok", "service": "stock-trading-system"})

    # ── Schwab OAuth bootstrap (one-time per 7-day refresh window) ──────
    # /oauth/schwab/start    → redirect to Schwab login (magic-link guarded)
    # /oauth/schwab/callback → exchange code for token, write to Volume
    # /api/schwab/diagnose   → smoke-test live API + report token age

    def _schwab_oauth_secret_ok() -> bool:
        cfg = get_config().get("schwab", {}) or {}
        expected = (cfg.get("oauth_secret")
                    or os.environ.get("SCHWAB_OAUTH_SECRET", ""))
        if not expected:
            return False  # Endpoint locked when no secret configured
        return request.args.get("secret") == expected

    @app.route("/oauth/schwab/start")
    def schwab_oauth_start():
        if not _schwab_oauth_secret_ok():
            return jsonify({"error": "forbidden"}), 403
        cfg = get_config().get("schwab", {}) or {}
        api_key = cfg.get("app_key") or os.environ.get("SCHWAB_APP_KEY", "")
        callback_url = (cfg.get("callback_url")
                        or os.environ.get("SCHWAB_CALLBACK_URL", ""))
        if not (api_key and callback_url):
            return jsonify({
                "error": "schwab not configured",
                "missing": [k for k, v in [
                    ("SCHWAB_APP_KEY", api_key),
                    ("SCHWAB_CALLBACK_URL", callback_url),
                ] if not v],
            }), 500
        from schwab.auth import get_auth_context
        try:
            ctx = get_auth_context(api_key, callback_url)
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": "auth_context_failed", "detail": str(e)}), 500
        from flask import session
        session["schwab_oauth_state"] = ctx.state
        session["schwab_oauth_callback_url"] = ctx.callback_url
        logger.info("Schwab OAuth start — redirecting to authorization URL")
        return redirect(ctx.authorization_url)

    @app.route("/oauth/schwab/callback")
    def schwab_oauth_callback():
        from flask import session
        from schwab.auth import AuthContext, client_from_received_url
        cfg = get_config().get("schwab", {}) or {}
        api_key = cfg.get("app_key") or os.environ.get("SCHWAB_APP_KEY", "")
        app_secret = (cfg.get("app_secret")
                      or os.environ.get("SCHWAB_APP_SECRET", ""))
        token_path = (cfg.get("token_path")
                      or os.environ.get("SCHWAB_TOKEN_PATH",
                                        "data/schwab_token.json"))

        expected_state = session.pop("schwab_oauth_state", None)
        callback_url = session.pop("schwab_oauth_callback_url", None) \
            or cfg.get("callback_url") \
            or os.environ.get("SCHWAB_CALLBACK_URL", "")
        received_state = request.args.get("state")
        if not expected_state or expected_state != received_state:
            logger.warning("Schwab OAuth state mismatch — rejecting callback")
            return jsonify({"error": "state_mismatch"}), 400

        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        ctx = AuthContext(callback_url=callback_url,
                          authorization_url="", state=expected_state)

        def _writer(token, *_args, **_kwargs):
            with open(token_path, "w") as f:
                json.dump(token, f)

        try:
            client_from_received_url(
                api_key=api_key, app_secret=app_secret,
                auth_context=ctx, received_url=request.url,
                token_write_func=_writer,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Schwab OAuth token exchange failed")
            return jsonify({"error": "token_exchange_failed",
                            "detail": str(e)[:300]}), 500

        # Reset cached managers so they pick up the new token immediately.
        global _data_manager, _data_router
        _data_manager = None
        _data_router = None
        logger.info("Schwab OAuth success — token written to %s", token_path)
        return jsonify({
            "status": "ok",
            "message": "Schwab token saved. Re-authorize within 7 days.",
            "token_path": token_path,
        })

    @app.route("/api/schwab/diagnose")
    def api_schwab_diagnose():
        """Smoke test for Schwab integration. Reports realtime + history + age."""
        import time as _t
        if not _schwab_oauth_secret_ok():
            return jsonify({"error": "forbidden"}), 403
        sch = _get_data_manager().get_schwab_provider()
        result: dict = {
            "enabled": sch.enabled,
            "token_age_days": sch.token_age_days(),
        }
        if not sch.enabled:
            result["error"] = "schwab provider disabled (missing token / config)"
            return jsonify(result), 503

        t0 = _t.perf_counter()
        single = sch.get_stock_price("AAPL")
        result["single_quote_ok"] = bool(single)
        result["single_quote_latency_ms"] = int((_t.perf_counter() - t0) * 1000)
        if single:
            result["single_quote_sample"] = {
                k: single.get(k) for k in ("ticker", "last", "close")
            }

        t0 = _t.perf_counter()
        batch = sch.get_stock_price_batch(["AAPL", "TSLA", "NVDA", "MSFT", "GOOG"])
        result["batch_quote_ok"] = len(batch) > 0
        result["batch_quote_count"] = len(batch)
        result["batch_quote_latency_ms"] = int((_t.perf_counter() - t0) * 1000)

        t0 = _t.perf_counter()
        df = sch.get_stock_history("AAPL", period="1mo", interval="1d")
        result["history_ok"] = df is not None and not df.empty
        result["history_bars"] = int(len(df)) if df is not None else 0
        result["history_latency_ms"] = int((_t.perf_counter() - t0) * 1000)

        return jsonify(result)

    # ── Dashboard API ───────────────────────────────────────────────────

    @app.route("/api/dashboard")
    def api_dashboard():
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        uid = g.user.id
        pm = _get_portfolio_mgr()
        pnl = pm.get_pnl(user_id=uid)
        holdings = pm.get_holdings(user_id=uid)
        alerts = _get_alert_monitor().list_alerts(user_id=uid, scope="user")
        # `history_days=all` returns the full series since the user's first
        # snapshot; the chart's range chips do client-side filtering on top.
        # Anything else is parsed as a positive int rolling window.
        raw_days = (request.args.get("history_days") or "all").strip().lower()
        if raw_days in ("", "all"):
            days: int | None = None
        else:
            try:
                parsed = int(raw_days)
                days = parsed if parsed > 0 else None
            except ValueError:
                days = 30
        history = pm.get_history(days=days, user_id=uid)
        # Provenance for the equity-curve card: the React island shows
        # an "insufficient snapshots — click 重新计算" notice when the
        # user has holdings but the daily_snapshots table can't draw a
        # multi-point curve. ``history_status`` lets the frontend make
        # that decision without a separate round-trip.
        first_date = history[0]["date"] if history else None
        last_date = history[-1]["date"] if history else None
        if holdings and len(history) <= 1:
            history_status = "insufficient_snapshots"
        else:
            history_status = "ok"
        return jsonify({
            "pnl": pnl,
            "holdings": holdings,
            "alerts_count": len(alerts),
            "history": history,
            "history_count": len(history),
            "history_first_date": first_date,
            "history_last_date": last_date,
            "history_status": history_status,
        })

    # ── Portfolio API ───────────────────────────────────────────────────

    @app.route("/api/portfolio/holdings")
    def api_holdings():
        return jsonify(_get_portfolio_mgr().get_holdings())

    def _validate_trade(data: dict, *, require_existing: bool,
                         user_id: int) -> str | None:
        """Return an error string if the trade payload is invalid, else None.

        Centralised so /add and /sell both reject the same shapes:
            * non-alphanumeric / empty ticker
            * shares <= 0 or price <= 0
            * (sell-only) ticker has no holding for this user, or shares
              exceed the holding — this prevents the "phantom sell" bug
              where /api/portfolio/sell silently recorded a transaction
              and left the user with a SELL row but no matching BUY.
        """
        ticker = (data.get("ticker") or "").strip().upper()
        # ".B" / "RDS-B" / "BRK.A" should pass; only allow alnum + . / -
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            return "ticker required and must be alphanumeric"
        try:
            shares = float(data.get("shares"))
            price = float(data.get("price"))
        except (TypeError, ValueError):
            return "shares and price must be numbers"
        if shares <= 0:
            return "shares must be > 0"
        if price <= 0:
            return "price must be > 0"
        if require_existing:
            from stock_trading_system.portfolio.database import PortfolioDatabase
            db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
            existing = PortfolioDatabase(db_path).get_position(ticker, user_id=user_id)
            if existing is None:
                return f"no position to sell for {ticker}"
            if shares > existing.shares + 1e-9:
                return f"sell shares ({shares}) exceeds holding ({existing.shares})"
        return None

    @app.route("/api/portfolio/add", methods=["POST"])
    def api_portfolio_add():
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.json or {}
        err = _validate_trade(data, require_existing=False, user_id=g.user.id)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        from stock_trading_system.utils.helpers import detect_market
        pm = _get_portfolio_mgr()
        ticker = data["ticker"].strip().upper()
        pm.add_position(
            ticker, float(data["shares"]), float(data["price"]),
            market=detect_market(ticker),
            date=data.get("date"), notes=data.get("notes", ""),
            user_id=g.user.id,
        )
        return jsonify({"ok": True, "message": f"BUY {data['shares']} {ticker} @ {data['price']}"})

    @app.route("/api/portfolio/sell", methods=["POST"])
    def api_portfolio_sell():
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.json or {}
        err = _validate_trade(data, require_existing=True, user_id=g.user.id)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        pm = _get_portfolio_mgr()
        ticker = data["ticker"].strip().upper()
        pm.sell_position(
            ticker, float(data["shares"]), float(data["price"]),
            date=data.get("date"), notes=data.get("notes", ""),
            user_id=g.user.id,
        )
        return jsonify({"ok": True, "message": f"SELL {data['shares']} {ticker} @ {data['price']}"})

    @app.route("/api/portfolio/transactions")
    def api_transactions():
        """Return this user's transactions in the contract the UI expects.

        Field contract (frozen for the React island):
            * ``action``     uppercase ``BUY`` / ``SELL`` (frontend colors
                             buys green, sells red on the literal upper-case
                             string)
            * ``timestamp``  canonical YYYY-MM-DD HH:MM:SS
            * ``date``       legacy alias of ``timestamp`` for older
                             callers; both fields point at the same value
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        ticker = request.args.get("ticker")
        rows = _get_portfolio_mgr().get_transactions(
            ticker=ticker, user_id=g.user.id,
        )
        out = []
        for t in rows:
            ts = t.get("timestamp") if isinstance(t, dict) else getattr(t, "timestamp", None)
            # PortfolioManager.get_transactions keys the timestamp as 'date'
            # for backwards compat; canonicalise to 'timestamp' here.
            if not ts and isinstance(t, dict):
                ts = t.get("date")
            action = (t.get("action") if isinstance(t, dict) else getattr(t, "action", "")) or ""
            out.append({
                "id":     t.get("id") if isinstance(t, dict) else getattr(t, "id", None),
                "ticker": t.get("ticker") if isinstance(t, dict) else getattr(t, "ticker", ""),
                "action": action.upper(),
                "shares": t.get("shares") if isinstance(t, dict) else getattr(t, "shares", 0),
                "price":  t.get("price") if isinstance(t, dict) else getattr(t, "price", 0),
                "timestamp": ts,
                "date":   ts,
                "notes":  (t.get("notes") if isinstance(t, dict) else getattr(t, "notes", "")) or "",
            })
        return jsonify(out)

    @app.route("/api/portfolio/pnl")
    def api_pnl():
        return jsonify(_get_portfolio_mgr().get_pnl())

    @app.route("/api/portfolio/allocation")
    def api_allocation():
        return jsonify(_get_portfolio_mgr().get_allocation())

    @app.route("/api/portfolio/summary")
    def api_portfolio_summary():
        """Aggregated portfolio stats for dashboard/portfolio page.

        ``today_pnl`` here is the **real** today's P&L — current portfolio
        value minus the most recent prior daily snapshot's ``total_value``.
        Returning ``total_pnl`` under the ``today_pnl`` key (the prior bug)
        was label-fraud: the dashboard tile said "今日 PnL" while showing
        cumulative P&L.

        ``today_pnl`` is ``None`` when there is no snapshot to diff against
        (fresh DB / first day) — the frontend then degrades the tile to
        "总盈亏" instead of guessing.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        uid = g.user.id
        pm = _get_portfolio_mgr()
        pnl = pm.get_pnl(user_id=uid)
        holdings = pm.get_holdings(user_id=uid)
        today_real = _compute_today_pnl(uid, pnl.get("total_value", 0))
        return jsonify({
            "total_value":    pnl.get("total_value", 0),
            "total_pnl":      pnl.get("total_pnl", 0),
            "total_pnl_pct":  pnl.get("total_pnl_pct", 0),
            "today_pnl":      today_real["pnl"] if today_real else None,
            "today_pnl_pct":  today_real["pct"] if today_real else None,
            "holdings_count": len(holdings),
        })

    def _compute_today_pnl(user_id: int, current_value: float) -> dict | None:
        """Return ``{pnl, pct}`` vs the most recent prior daily snapshot.

        Returns ``None`` when no usable prior snapshot exists (fresh user,
        only today's snapshot, or prior total_value <= 0). The caller
        surfaces ``None`` directly so the UI can render a degraded tile
        instead of a misleading zero.
        """
        from stock_trading_system.portfolio.database import PortfolioDatabase
        from stock_trading_system.utils.helpers import today_str
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        rows = db.get_snapshots(user_id=user_id, days=2)
        if not rows:
            return None
        today = today_str()
        prev = None
        for r in reversed(rows):
            r_date = r.date if hasattr(r, "date") else r.get("date")
            if r_date != today:
                prev = r
                break
        if prev is None:
            return None
        prev_value = float(getattr(prev, "total_value", None)
                            if hasattr(prev, "total_value")
                            else prev.get("total_value") or 0)
        if prev_value <= 0:
            return None
        diff = current_value - prev_value
        return {"pnl": round(diff, 2), "pct": round(diff / prev_value * 100, 2)}

    @app.route("/api/portfolio/<ticker>", methods=["DELETE"])
    def api_portfolio_delete(ticker):
        """Remove a position entirely."""
        pm = _get_portfolio_mgr()
        pm.remove_position(ticker.upper())
        return jsonify({"ok": True})

    @app.route("/api/portfolio/history")
    def api_history():
        days = request.args.get("days", 30, type=int)
        return jsonify(_get_portfolio_mgr().get_history(days=days))

    # ── Analysis API ────────────────────────────────────────────────────

    @app.route("/api/analyze", methods=["POST"])
    def api_analyze():
        """Legacy /api/analyze: forwards to TaskManager.

        v1.14 unifies all analysis through the same pipeline as /api/tasks/submit
        + the analysis worker + Pipeline DAG events. Old clients that POST here
        receive the same {task_id, status} envelope and can subscribe to
        /api/tasks/<task_id> for progress.

        The previous implementation spawned a daemon thread, emitted three
        bespoke socket events (analysis_status / analysis_result /
        analysis_error), and wrote analysis_history directly with a
        hard-coded gemini.deep_think_model — none of which matched the
        unified flow workers go through. All of that is gone.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        data = request.json or {}
        ticker = (data.get("ticker") or "").upper().strip()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        from stock_trading_system.utils.helpers import today_str
        from stock_trading_system.portfolio.database import _normalize_depth
        date = data.get("date") or today_str()
        depth = _normalize_depth(data.get("depth"))

        tm = _get_task_manager()
        params = {
            "ticker": ticker,
            "date": date,
            "depth": depth,
            "__user_id__": g.user.id,
        }
        task = tm.submit(
            task_type="analysis",
            params=params,
            title=f"AI 分析 · {ticker}",
            created_by=g.user.id,
        )
        return jsonify({"task_id": task["id"], "status": "queued"})

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
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(_get_alert_monitor().list_alerts(
            user_id=g.user.id, scope="user",
        ))

    @app.route("/api/alerts/add", methods=["POST"])
    def api_alert_add():
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        data = request.json
        monitor = _get_alert_monitor()
        monitor.add_alert(
            data["ticker"].upper(), data["condition"], float(data["threshold"]),
            user_id=g.user.id,
        )
        return jsonify({"ok": True, "message": f"Alert added: {data['ticker']} {data['condition']} {data['threshold']}"})

    @app.route("/api/alerts/remove", methods=["POST"])
    def api_alert_remove():
        data = request.json
        _get_alert_monitor().remove_alert(int(data["id"]))
        return jsonify({"ok": True})

    @app.route("/api/alerts/check", methods=["POST"])
    def api_alert_check():
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        triggered = _get_alert_monitor().check_alerts(
            user_id=g.user.id, scope="user",
        )
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
        """List recent analyses for the unified /analysis inbox.

        v1.22: when ``include_running=true`` the response also carries
        the requesting user's in-flight ``analysis`` tasks merged into
        the same list under ``kind: "task"`` rows; completed
        ``analysis_history`` rows under ``kind: "analysis"``. Dedupes
        by ``task_id`` so a row that landed in ``analysis_history`` but
        whose source task is still in ``pending``/``running``/``failed``
        doesn't appear twice.

        Without ``include_running`` the legacy v1.18 contract holds —
        ``{items, records, count}`` of completed analyses only — so any
        unauthenticated dashboard / legacy caller keeps working.

        SECURITY: running tasks are user-scoped via TaskStore so a
        tenant never sees another tenant's in-flight submission.
        """
        from stock_trading_system.portfolio.database import (
            PortfolioDatabase, _normalize_depth,
        )

        ticker = request.args.get("ticker")
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 200))
        except ValueError:
            return jsonify({"error": "limit must be int"}), 400
        include_running = (
            (request.args.get("include_running") or "").lower() == "true"
        )

        # Login required ONLY when the inbox shape is requested. Preserves
        # the legacy unauthenticated callers of the simple list contract.
        if include_running and g.user is None:
            return jsonify({"error": "unauthorized"}), 401

        db_path = get_config().get("portfolio", {}).get(
            "db_path", "data/portfolio.db",
        )
        db = PortfolioDatabase(db_path)

        # Resolve display_name via the user repo (cache per request).
        cache: dict[int, str] = {}

        def _name(uid):
            if uid is None:
                return None
            if uid not in cache:
                try:
                    user = _user_repo.find_by_id(int(uid))
                    cache[uid] = (user.display_name or user.email) if user else ""
                except Exception:  # noqa: BLE001
                    cache[uid] = ""
            return cache[uid] or None

        # ── 1. Active tasks (when requested) ─────────────────────────
        running_items: list[dict] = []
        running_task_ids: set[str] = set()
        if include_running:
            try:
                store = _get_task_store()
                active = store.list_tasks_by_user_and_type(
                    user_id=g.user.id, task_type="analysis",
                    statuses=("pending", "running", "failed", "cancelled"),
                    limit=20,
                )
                for t in active:
                    raw_params = t.get("params_json") or "{}"
                    try:
                        p = json.loads(raw_params)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(
                            "inbox: task %s params_json parse failed: %s",
                            t.get("id"), e,
                        )
                        p = {}
                    cb_raw = t.get("created_by")
                    cb_int: int | None
                    try:
                        cb_int = int(cb_raw) if cb_raw and str(cb_raw).isdigit() else None
                    except (TypeError, ValueError):
                        cb_int = None
                    running_items.append({
                        "kind":              "task",
                        "task_id":           t["id"],
                        "ticker":            (p.get("ticker") or "").upper(),
                        "depth":             _normalize_depth(p.get("depth")),
                        "status":            t.get("status", "pending"),
                        "submitted_at":      t.get("created_at"),
                        "task_started_at":   t.get("started_at"),
                        "progress_pct":      int(t.get("progress") or 0),
                        "progress_step":     t.get("progress_step"),
                        "error":             t.get("error_message"),
                        "created_by":        cb_int,
                        "created_by_name":   _name(cb_int),
                    })
                    running_task_ids.add(str(t["id"]))
            except Exception as e:  # noqa: BLE001
                logger.warning("inbox running fetch failed: %s", e)

        # ── 2. Completed analysis_history rows ───────────────────────
        # ``get_analysis_history`` doesn't filter by user — we keep the
        # shared-research model (everyone sees the corpus). Per-user
        # bookmark / private advice still resolved per requester.
        records = db.get_analysis_history(ticker=ticker, limit=limit)
        # Drop any completed row whose ``task_id`` is currently active —
        # the running row carries the live state and is the source of
        # truth until the task settles.
        if running_task_ids:
            records = [
                r for r in records
                if not (r.get("task_id")
                         and str(r["task_id"]) in running_task_ids)
            ]

        completed_items = [{
            "kind":             "analysis",
            "id":               rec.get("id"),
            "ticker":           rec.get("ticker"),
            "date":             rec.get("date"),
            "signal":           rec.get("signal"),
            "created_at":       rec.get("created_at"),
            "created_by":       rec.get("created_by"),
            "created_by_name":  _name(rec.get("created_by")),
            "provider":         rec.get("provider"),
            "model":            rec.get("model"),
            "duration_sec":     rec.get("duration_sec"),
            "task_id":          rec.get("task_id"),
            "bookmarked":       bool(rec.get("bookmarked")),
            "depth":            _normalize_depth(rec.get("depth")),
        } for rec in records]

        if include_running:
            # ``submitted_at`` for tasks, ``created_at`` for analyses —
            # both are wall-clock strings comparable lexicographically
            # since they're stored as ``YYYY-MM-DD HH:MM:SS``.
            merged = sorted(
                running_items + completed_items,
                key=lambda x: (
                    x.get("submitted_at") or x.get("created_at") or ""
                ),
                reverse=True,
            )
            return jsonify({
                "items":            merged,
                "running_total":    len(running_items),
                "completed_total":  len(completed_items),
                "limit":            limit,
            })

        # Legacy v1.18 contract: completed only, no ``kind`` discriminator.
        legacy_items = [
            {k: v for k, v in it.items() if k != "kind"}
            for it in completed_items
        ]
        return jsonify({
            "items":   legacy_items,
            "records": legacy_items,
            "count":   len(legacy_items),
        })

    @app.route("/api/history/<int:analysis_id>")
    def api_analysis_detail(analysis_id):
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        record = db.get_analysis_by_id(analysis_id)
        if not record:
            return jsonify({"error": "Not found"}), 404

        # Per-user advice (v1.14): the shared row no longer holds a
        # holdings-aware position-sizing payload. Pull the current user's
        # row out of user_analysis_advice instead.
        user_id = g.user.id if g.user else None
        user_advice = None
        bookmarked = False
        if user_id is not None:
            user_advice = db.get_user_advice(user_id, analysis_id)
            bookmarked = db.is_bookmarked(user_id, analysis_id)

        # Resolve created_by → display_name (fallback to email).
        created_by_name = None
        creator_id = record.get("created_by")
        if creator_id:
            try:
                user = _user_repo.find_by_id(int(creator_id))
                if user:
                    created_by_name = user.display_name or user.email
            except Exception as e:  # noqa: BLE001
                logger.warning("created_by lookup failed: %s", e)

        # advice is the requesting user's private row only — the shared
        # analysis_history row no longer carries advice_json (post-v1.16
        # migration hoists pre-existing legacy advice into
        # user_analysis_advice keyed on the original creator). If the
        # requester has no advice row, the response just shows an empty
        # advice dict; another tenant's plan never leaks here.
        advice: dict = {}
        if user_advice:
            for key in ("action", "confidence", "position_pct",
                        "entry_low", "entry_high", "stop_loss", "take_profit",
                        "reasoning", "risk_warning"):
                if user_advice.get(key) is not None:
                    advice[key] = user_advice[key]

        analysts = {}
        for key in ("market_report", "sentiment_report", "news_report",
                     "fundamentals_report", "investment_debate", "risk_assessment"):
            if record.get(key):
                analysts[key.replace("_report", "").replace("_", " ").title()] = record[key]

        # confidence string → numeric for the gauge UI. Pull from the
        # per-user advice row, never the shared (and now-empty) column.
        conf_str = (advice.get("confidence") or "").lower() if isinstance(advice.get("confidence"), str) else ""
        conf_map = {"high": 0.85, "medium": 0.5, "low": 0.25}
        confidence_num = conf_map.get(conf_str)

        # v1.20 trade-action consistency: parse the trader's explicit
        # ``FINAL TRANSACTION PROPOSAL: **X**`` from ``trade_decision``.
        # New rows (post-v1.20) already store the parsed action in
        # ``signal``, so ``decision_action == signal`` for them; old
        # rows where ``graph.process_signal`` disagreed with the
        # trader's text surface a ``signal_mismatch=true`` flag so the
        # frontend can correct itself + show a "已校正" hint.
        from stock_trading_system.agents.iterative.signal_extractor import (
            extract_trade_action,
        )
        decision_action = extract_trade_action(record.get("trade_decision"))
        stored_signal = (record.get("signal") or "").strip()
        signal_mismatch = bool(
            decision_action
            and stored_signal
            and stored_signal.lower() != decision_action.lower()
        )

        # Whitelisted DTO — never echo the raw row, which carries shared
        # advice columns whose values would have leaked across users on
        # pre-v1.14 records.
        from stock_trading_system.portfolio.database import _normalize_depth
        return jsonify({
            "id":                 record.get("id"),
            "ticker":             record.get("ticker"),
            "date":               record.get("date"),
            "signal":             record.get("signal"),
            "decision_action":    decision_action,
            "signal_mismatch":    signal_mismatch,
            "created_at":         record.get("created_at"),
            "created_by":         creator_id,
            "created_by_name":    created_by_name,
            "provider":           record.get("provider"),
            "model":              record.get("model"),
            "duration_sec":       record.get("duration_sec"),
            "task_id":            record.get("task_id"),
            "config_hash":        record.get("config_hash"),
            "depth":              _normalize_depth(record.get("depth")),
            "executive_summary":  record.get("executive_summary"),
            "summary":            record.get("executive_summary") or record.get("trade_decision") or "",
            "recommendation":     record.get("trade_decision") or "",
            "trade_decision":     record.get("trade_decision") or "",
            "market_report":      record.get("market_report") or "",
            "sentiment_report":   record.get("sentiment_report") or "",
            "news_report":        record.get("news_report") or "",
            "fundamentals_report": record.get("fundamentals_report") or "",
            "investment_debate":  record.get("investment_debate") or "",
            "risk_assessment":    record.get("risk_assessment") or "",
            "analysts":           analysts,
            "confidence":         confidence_num,
            "risk_level":         advice.get("risk_level") or conf_str or "-",
            "advice":             advice or None,
            "bookmarked":         bookmarked,
            # v1.19: per-tab structured cards. Always parse the stored JSON
            # into a dict before exposing — never echo ``rendering_json``
            # itself, that's a storage detail and could trip clients
            # expecting structured data.
            "rendering":          _parse_rendering(record.get("rendering_json")),
            # v1.7 (2026-05-06): structured-summary state machine. The
            # frontend uses ``rendering_status`` to choose between the
            # structured cards and the markdown fallback (success/partial
            # → cards primary, failed/empty/pending → markdown primary +
            # retry banner). ``rendering_available_tabs`` lets the UI
            # show a per-tab badge when only some cards rendered.
            "rendering_status":   record.get("rendering_status")
                                    or _infer_rendering_status_legacy(record),
            "rendering_error":    record.get("rendering_error"),
            "rendering_generated_at": record.get("rendering_generated_at"),
            "rendering_available_tabs":
                _rendering_available_tabs(record.get("rendering_json")),
        })

    def _merge_user_advice_into_records(db, records: list[dict],
                                         user_id: int | None) -> list[dict]:
        """Layer this user's private advice onto shared compare/timeline rows.

        The shared row never carries advice (post-v1.16) — _STRUCTURED_COLS
        only selects shared research columns. We project the requesting
        user's ``user_analysis_advice`` row, if any, into a nested
        ``my_advice`` field. Other users' advice is never visible.
        """
        if not records:
            return []
        ids = [int(r["id"]) for r in records if r.get("id") is not None]
        advice_by_id: dict[int, dict] = {}
        if user_id is not None and ids:
            try:
                advice_by_id = db.get_user_advice_bulk(user_id, ids)
            except Exception as e:  # noqa: BLE001
                logger.warning("get_user_advice_bulk failed: %s", e)
                advice_by_id = {}
        out = []
        for r in records:
            row = dict(r)
            row["bookmarked"] = bool(row.get("bookmarked"))
            adv = advice_by_id.get(int(row["id"])) if row.get("id") else None
            if adv:
                row["my_advice"] = {
                    "action":        adv.get("action"),
                    "confidence":    adv.get("confidence"),
                    "position_pct":  adv.get("position_pct"),
                    "entry_low":     adv.get("entry_low"),
                    "entry_high":    adv.get("entry_high"),
                    "stop_loss":     adv.get("stop_loss"),
                    "take_profit":   adv.get("take_profit"),
                }
            else:
                row["my_advice"] = None
            out.append(row)
        return out

    @app.route("/api/history/compare")
    def api_analysis_compare():
        """Compare multiple analyses side-by-side. Query: ?ids=1,2,3 (up to 5).

        Shared columns only (v1.16) — per-user advice (action/confidence/
        entry/stop/take_profit/position_pct) is never embedded directly
        on the row. The current user's own advice, if any, is layered
        in via ``my_advice``; other users' advice is never visible.
        """
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
        uid = g.user.id if getattr(g, "user", None) else None
        records = db.get_analyses_by_ids(ids)
        records = _merge_user_advice_into_records(db, records, uid)
        return jsonify({"count": len(records), "records": records})

    @app.route("/api/history/timeline/<ticker>")
    def api_analysis_timeline(ticker):
        """Structured chronological history for one ticker (drift view).

        See ``api_analysis_compare`` for the shared/private contract.
        """
        from stock_trading_system.portfolio.database import PortfolioDatabase
        limit = int(request.args.get("limit", 20))
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        uid = g.user.id if getattr(g, "user", None) else None
        records = db.get_analysis_timeline(ticker.upper(), limit=limit)
        records = _merge_user_advice_into_records(db, records, uid)
        return jsonify({"ticker": ticker.upper(), "count": len(records),
                         "records": records})

    @app.route("/api/history/<int:analysis_id>", methods=["DELETE"])
    def api_analysis_delete(analysis_id):
        """Delete a shared analysis row.

        Only the original creator (``created_by == g.user.id``) or an
        admin may delete. Anyone else gets 403 — the analysis library is
        shared research, not a personal scratch pad.
        """
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        creator_id = db.get_analysis_creator(analysis_id)
        if creator_id is None:
            # Could be 404 (no such row) or legacy row with no created_by.
            # Treat both as 404; only admin may force-delete via DB tooling.
            row = db.get_analysis_by_id(analysis_id)
            if not row:
                return jsonify({"ok": False, "error": "not_found"}), 404
            if g.user.role != "admin":
                return jsonify({"ok": False, "error": "forbidden"}), 403
        elif creator_id != g.user.id and g.user.role != "admin":
            return jsonify({"ok": False, "error": "forbidden"}), 403
        ok = db.delete_analysis(analysis_id)
        return jsonify({"ok": ok})

    # ── E of v1.14: export + bookmark + track ────────────────────────────

    def _render_analysis_markdown(rec: dict) -> str:
        """Stitch the 8 report sections into one markdown blob.

        Used by the export endpoint. Pure formatting — no HTML, no script
        injection surface; rehype-sanitize on the read path is the second
        layer if anyone ever pipes this back through Markdown.
        """
        ticker = rec.get("ticker", "")
        date = rec.get("date", "")
        signal = rec.get("signal", "")
        provider = rec.get("provider") or ""
        model = rec.get("model") or ""
        lines = [
            f"# {ticker} · AI 分析",
            "",
            f"- **日期**: {date}",
            f"- **信号**: {signal}",
            f"- **Provider**: {provider} / {model}".rstrip(" /"),
            f"- **生成时间**: {rec.get('created_at', '')}",
            "",
        ]
        for header, key in [
            ("市场 / 技术面", "market_report"),
            ("情绪面", "sentiment_report"),
            ("新闻", "news_report"),
            ("基本面", "fundamentals_report"),
            ("多空辩论", "investment_debate"),
            ("风险评估", "risk_assessment"),
            ("决策", "trade_decision"),
        ]:
            body = rec.get(key) or ""
            if body:
                lines.append(f"## {header}")
                lines.append("")
                lines.append(str(body))
                lines.append("")
        return "\n".join(lines)

    @app.route("/api/history/<int:analysis_id>/export")
    def api_history_export(analysis_id):
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        fmt = (request.args.get("format") or "md").lower()
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        rec = db.get_analysis_by_id(analysis_id)
        if not rec:
            return jsonify({"error": "not found"}), 404

        md = _render_analysis_markdown(rec)
        filename_base = f"{rec.get('ticker', 'analysis')}-{rec.get('date', 'undated')}"
        if fmt == "md":
            return Response(
                md, mimetype="text/markdown",
                headers={
                    "Content-Disposition":
                        f'attachment; filename="{filename_base}.md"',
                },
            )
        if fmt == "pdf":
            try:
                # WeasyPrint is heavy + has system deps. We treat it as
                # opt-in; the markdown export always works and is the
                # safer default.
                from weasyprint import HTML  # type: ignore[import-not-found]
                import markdown as md_lib  # type: ignore[import-not-found]
            except ImportError:
                return jsonify({
                    "error": "pdf_unavailable",
                    "message": "PDF export requires weasyprint + markdown; "
                               "install via `pip install weasyprint markdown` "
                               "and restart. Markdown export still works.",
                }), 501
            html = md_lib.markdown(md, extensions=["tables", "fenced_code"])
            pdf_bytes = HTML(string=html).write_pdf()
            return Response(
                pdf_bytes, mimetype="application/pdf",
                headers={
                    "Content-Disposition":
                        f'attachment; filename="{filename_base}.pdf"',
                },
            )
        return jsonify({"error": "format must be md|pdf"}), 400

    @app.route("/api/history/<int:analysis_id>/rendering/retry", methods=["POST"])
    def api_rendering_retry(analysis_id):
        """v1.7 — enqueue a structured-summary backfill for one row.

        Used by the "重新生成结构化摘要" button on the detail page when
        ``rendering_status`` is ``failed`` / ``empty`` / ``pending``.
        Returns the new ``analysis_rendering_backfill`` task_id so the
        UI can subscribe to its completion event and refresh the page.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        record = db.get_analysis_by_id(analysis_id)
        if not record:
            return jsonify({"error": "not found"}), 404
        # Anyone logged in can retry — it's idempotent and only writes
        # to the rendering columns. ``analysis_history`` is shared
        # research, so non-owners benefit from the structured cards too.
        tm = _get_task_manager()
        task = tm.submit(
            task_type="analysis_rendering_backfill",
            params={"analysis_id": int(analysis_id)},
            title=f"补结构化摘要 #{analysis_id}",
            created_by=g.user.id,
        )
        return jsonify({
            "ok": True,
            "task_id": task["id"],
            "id": task["id"],
            "analysis_id": int(analysis_id),
        })


    @app.route("/api/history/<int:analysis_id>/bookmark", methods=["POST"])
    def api_bookmark_toggle(analysis_id):
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        bookmarked = bool(body.get("bookmarked", True))
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        # Confirm the analysis exists; otherwise the FK constraint would
        # mask the real "wrong id" with a generic error.
        if not db.get_analysis_by_id(analysis_id):
            return jsonify({"error": "not found"}), 404
        new_state = db.set_bookmark(g.user.id, analysis_id, bookmarked)
        return jsonify({"ok": True, "bookmarked": new_state})

    @app.route("/api/portfolio/track", methods=["POST"])
    def api_portfolio_track():
        """Add a ticker to the user's lightweight watchlist + audit-link
        the originating analysis. Does NOT touch the paper-trade session
        store — that integration lives in /api/paper/track and is heavier.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        ticker = (body.get("ticker") or "").upper().strip()
        analysis_id = body.get("analysis_id")
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        try:
            analysis_id_int = int(analysis_id) if analysis_id is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "analysis_id must be int"}), 400
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        db.add_to_watchlist(
            user_id=g.user.id, ticker=ticker, analysis_id=analysis_id_int,
        )
        return jsonify({"ok": True, "ticker": ticker, "analysis_id": analysis_id_int})

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

    def _days_to_period(days: int) -> str:
        """Map a day window to the closest yfinance/Schwab `period` string."""
        if days <= 7:
            return "5d"
        if days <= 31:
            return "1mo"
        if days <= 95:
            return "3mo"
        if days <= 190:
            return "6mo"
        if days <= 380:
            return "1y"
        if days <= 760:
            return "2y"
        return "5y"

    def _ohlcv_rows(df) -> list[dict]:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        rows: list[dict] = []
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
        return rows

    @app.route("/api/quote/history")
    def api_quote_history():
        """OHLCV bars for K-line rendering (TVChart / lightweight-charts).

        Query params:
            ticker: required, stock symbol
            days:   rolling window size (default 90); mapped to provider period

        Returns ``{ticker, days, bars: [{date,open,high,low,close,volume}, ...]}``.
        Empty ``bars`` (rather than 404) lets the frontend show the chart
        skeleton without tripping its error path.
        """
        ticker = (request.args.get("ticker") or "").strip().upper()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        try:
            days = int(request.args.get("days", 90))
        except (TypeError, ValueError):
            days = 90
        days = max(1, min(days, 1825))  # clamp to ~5y
        period = _days_to_period(days)
        try:
            df = _get_data_manager().get_history(ticker, period=period, interval="1d")
        except Exception as e:  # noqa: BLE001
            logger.warning("/api/quote/history failed for %s: %s", ticker, e)
            return jsonify({"ticker": ticker, "days": days, "bars": [], "error": str(e)}), 200
        bars = _ohlcv_rows(df) if (df is not None and len(df) > 0) else []
        return jsonify({"ticker": ticker, "days": days, "bars": bars})

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

    @app.route("/api/analysis/<int:analysis_id>/quick-info")
    def api_analysis_quick_info(analysis_id):
        """Aggregated quick-info card for the analysis detail page.

        Bundles the news + fundamentals lookups the AnalysisDetailView
        used to fire as two separate XHRs into a single response. Both
        upstream providers are best-effort — failures degrade to empty
        / null rather than 500ing the whole page so the rest of the
        detail still renders.
        """
        from stock_trading_system.portfolio.database import PortfolioDatabase
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)
        record = db.get_analysis_by_id(analysis_id)
        if not record:
            return jsonify({"error": "not_found"}), 404
        ticker = (record.get("ticker") or "").upper()

        news: list = []
        if ticker:
            try:
                raw = _get_data_manager().get_news(ticker) or []
                # Top 3 only — quick-info card doesn't paginate.
                news = list(raw)[:3]
            except Exception as e:  # noqa: BLE001
                logger.warning("quick-info news failed for %s: %s", ticker, e)

        fundamentals = None
        if ticker:
            try:
                fundamentals = _get_data_manager().get_fundamentals(ticker)
            except Exception as e:  # noqa: BLE001
                logger.warning("quick-info fundamentals failed for %s: %s", ticker, e)

        return jsonify({
            "ticker": ticker,
            "news": news,
            "fundamentals": fundamentals,
        })

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

    @app.route("/api/portfolio/snapshots/backfill", methods=["POST"])
    def api_portfolio_snapshots_backfill():
        """Submit a backfill task that replays transactions into daily_snapshots.

        Body: ``{"from": "earliest" | "<YYYY-MM-DD>", "force": bool}``
        Returns ``{"task_id": "...", "task": {...}}`` so the frontend can
        subscribe to its progress through the unified-progress stream.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True) or {}
        params = {
            "user_id": g.user.id,
            "from": body.get("from", "earliest"),
            "force": bool(body.get("force", False)),
        }
        tm = _get_task_manager()
        task = tm.submit(
            "backfill_snapshots", params,
            title=f"回填净值快照 · user={g.user.id}",
            created_by=g.user.id,
        )
        return jsonify({"ok": True, "task_id": task["id"], "task": task})

    # ── Scheduler Control ───────────────────────────────────────────────

    def _last_snapshot_at(uid: int | None) -> str | None:
        """MAX(date) FROM daily_snapshots — surfaced in /api/scheduler/status."""
        import sqlite3 as _sql
        path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        try:
            conn = _sql.connect(path)
        except _sql.OperationalError:
            return None
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_snapshots)").fetchall()}
            if uid is not None and "user_id" in cols:
                row = conn.execute(
                    "SELECT MAX(date) FROM daily_snapshots WHERE user_id = ?", (uid,),
                ).fetchone()
            else:
                row = conn.execute("SELECT MAX(date) FROM daily_snapshots").fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _daily_snapshot_scheduler():
        """Return the APScheduler singleton if the boot path wired it up."""
        from stock_trading_system.scheduler.daily_snapshot_scheduler import (
            DailySnapshotScheduler,
        )
        try:
            return DailySnapshotScheduler.get()
        except RuntimeError:
            return None

    @app.route("/api/scheduler/status")
    def api_scheduler_status():
        """Combined status: legacy alert/report scheduler + APScheduler daily job."""
        global _scheduler_thread
        sched = _get_scheduler()
        alive = _scheduler_thread is not None and _scheduler_thread.is_alive()
        legacy = {
            "running": bool(alive and sched.is_running),
            "thread_alive": bool(alive),
            "alert_interval": sched._alert_interval,
        }
        # APScheduler daily-snapshot details (the field /api/scheduler/run-now
        # actually fires).
        apsched_payload: dict
        ap = _daily_snapshot_scheduler()
        if ap is None:
            apsched_payload = {"running": False, "jobs": [], "primary": False, "pid": None}
        else:
            apsched_payload = ap.status()
        uid = g.user.id if g.user else None
        return jsonify({
            **legacy,
            "running": bool(legacy["running"] or apsched_payload.get("running")),
            "jobs": apsched_payload.get("jobs", []),
            "primary": apsched_payload.get("primary", False),
            "pid": apsched_payload.get("pid"),
            "last_run": _last_snapshot_at(uid),
            "legacy": legacy,
        })

    @app.route("/api/scheduler/run-now", methods=["POST"])
    @admin_required
    def api_scheduler_run_now():
        """Fire the daily-snapshot job immediately (admin-only)."""
        ap = _daily_snapshot_scheduler()
        if ap is None:
            return jsonify({"ok": False, "error": "scheduler not initialized"}), 503
        result = ap.run_now()
        return jsonify({"ok": True, "result": result})

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
        openrouter = cfg.get("openrouter", {}) or {}
        telegram = (cfg.get("alerts", {}) or {}).get("telegram", {}) or {}
        email = (cfg.get("alerts", {}) or {}).get("email", {}) or {}
        portfolio_cfg = cfg.get("portfolio", {}) or {}

        qwen_active = bool(qwen.get("enabled") and qwen.get("api_key"))
        # v1.0: OR is "active" (i.e. has a usable key) when env or yaml
        # provides one; the enabled flag is treated as advisory rather
        # than gating because the env-only cloud path doesn't write yaml.
        or_active = bool(
            os.environ.get("OPENROUTER_API_KEY")
            or openrouter.get("api_key")
        )

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
            "openrouter": {
                "enabled": bool(openrouter.get("enabled")),
                # ``active`` is a *boolean* here — true when env or yaml
                # provides a usable api_key. The deep/quick pointer dict
                # is reported as ``active_pointers`` to avoid colliding
                # with this boolean in the DTO. (The /openrouter/active
                # endpoint pair uses the dict shape natively because
                # there's no boolean to collide with there.)
                "active":  or_active,
                "base_url": openrouter.get("base_url",
                    "https://openrouter.ai/api/v1"),
                "http_referer": openrouter.get("http_referer", ""),
                "x_title":      openrouter.get("x_title", ""),
                "timeout":      int(openrouter.get("timeout", 120)),
                "api_key_masked": _mask_secret(openrouter.get("api_key", "")),
                # presets[] / active_pointers{} surface for the
                # SettingsPage OpenRouter table; mutations go through
                # /api/settings/openrouter/active (single-preset) or a
                # future /api/settings/openrouter/presets bulk endpoint.
                "presets": [
                    {
                        "id":             p.get("id"),
                        "label":          p.get("label"),
                        "model":          p.get("model"),
                        "role":           p.get("role"),
                        "provider_order": p.get("provider_order") or [],
                        "kwargs":         p.get("kwargs") or {},
                    }
                    for p in (openrouter.get("presets") or [])
                ],
                "active_pointers": openrouter.get("active") or {},
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

        Per-user isolation: positions / transactions / alerts are scoped to
        ``g.user.id`` so two users with overlapping tickers cannot leak rows
        across tenants. ``analysis_history`` stays shared (it's the research
        library — per-user advice lives in ``user_analysis_advice``).

        Transactions DO NOT index ``notes`` — those are private free-text
        and indexing them would expose another user's thesis through any
        casual substring query.
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
        uid = g.user.id if getattr(g, "user", None) else None

        # Positions — read rows directly so we don't trigger live price fetches.
        positions_out = []
        try:
            for p in db.get_all_positions(user_id=uid):
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

        # Transactions — ticker + action only. Notes are private; never index.
        transactions_out = []
        try:
            for t in db.get_transactions(user_id=uid):
                hay = f"{t.ticker} {t.action}".lower()
                if q in hay:
                    transactions_out.append({
                        "id": t.id, "ticker": t.ticker,
                        "action": (t.action or "").upper(),
                        "shares": t.shares, "price": t.price,
                        "timestamp": t.timestamp, "notes": t.notes,
                    })
                if len(transactions_out) >= limit:
                    break
        except Exception as e:
            logger.warning("search transactions failed: %s", e)

        # Analysis history — shared research library, no per-user filter.
        # Per-user advice fields (action/confidence) live in user_analysis_advice
        # so we deliberately don't surface them here in a cross-user search.
        analyses_out = []
        try:
            for r in db.get_analysis_history(limit=500):
                hay = " ".join(
                    str(r.get(k) or "") for k in ("ticker", "signal", "model")
                ).lower()
                if q in hay:
                    analyses_out.append({
                        "id": r.get("id"),
                        "ticker": r.get("ticker"),
                        "date": r.get("date"),
                        "signal": r.get("signal"),
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
            for a in db.get_active_alerts(user_id=uid):
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

    # v1.0 (2026-05-05): three-state LLM switch — qwen / gemini / openrouter.
    # GET adds has_openrouter_key so the UI can disable the OR option when
    # neither yaml api_key nor OPENROUTER_API_KEY env is set. POST validates
    # provider against VALID_PROVIDERS (which now includes 'openrouter').
    _PROVIDER_LABEL = {"qwen": "Qwen", "gemini": "Gemini", "openrouter": "OpenRouter"}

    @app.route("/api/settings/llm-provider", methods=["GET"])
    def get_llm_provider():
        from stock_trading_system.llm.router import (
            get_active_provider, has_provider_key, is_provider_locked_by_env,
        )
        cfg = get_config()
        return jsonify({
            "active":             get_active_provider(cfg),
            "has_qwen_key":       has_provider_key(cfg, "qwen"),
            "has_gemini_key":     has_provider_key(cfg, "gemini"),
            "has_openrouter_key": has_provider_key(cfg, "openrouter"),
            "locked_by_env":      is_provider_locked_by_env(),
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
            label = _PROVIDER_LABEL.get(provider, provider)
            return jsonify({
                "reason":  "missing_api_key",
                "message": f"{label} 未配置 API key",
            }), 400
        save_config({"llm_provider": provider})
        # Reset analyzer so next analysis uses new provider
        _reset_config_dependent_singletons(["llm_provider"])
        return jsonify({"active": provider, "source": "user_config"})

    # ── OpenRouter active preset switch (deep / quick) ───────────────
    #
    # The provider switch (above) only flips qwen|gemini|openrouter.
    # When OR is active, this endpoint surfaces the preset pool and
    # lets the UI swap which preset is active for deep / quick roles
    # without leaving the page. Persists to yaml the same way the
    # provider switch does (via save_config + _reset_config_dependent_
    # singletons).

    @app.route("/api/settings/openrouter/active", methods=["GET"])
    def get_openrouter_active():
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        from stock_trading_system.llm.router import (
            get_active_provider, resolve_openrouter_model,
        )
        cfg = get_config()
        or_cfg = cfg.get("openrouter") or {}
        return jsonify({
            "deep":    resolve_openrouter_model(cfg, role="deep"),
            "quick":   resolve_openrouter_model(cfg, role="quick"),
            "presets": [
                {
                    "id":             p.get("id"),
                    "label":          p.get("label"),
                    "model":          p.get("model"),
                    "role":           p.get("role"),
                    "provider_order": p.get("provider_order") or [],
                    "kwargs":         p.get("kwargs") or {},
                }
                for p in (or_cfg.get("presets") or [])
            ],
            "active":          or_cfg.get("active") or {},
            "active_provider": "openrouter" if get_active_provider(cfg) == "openrouter" else None,
        })

    @app.route("/api/settings/openrouter/active", methods=["POST"])
    def set_openrouter_active():
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        from stock_trading_system.llm.router import is_provider_locked_by_env
        if is_provider_locked_by_env():
            return jsonify({
                "reason":  "locked_by_env",
                "message": "LLM_PROVIDER 已由环境变量锁定",
            }), 409
        body = request.get_json(silent=True) or {}
        role = (body.get("role") or "").strip().lower()
        preset_id = (body.get("preset_id") or "").strip()
        if role not in ("deep", "quick"):
            return jsonify({
                "reason":  "invalid_role",
                "message": "role 必须是 deep|quick",
            }), 400
        cfg = get_config()
        or_cfg = cfg.get("openrouter") or {}
        presets = {p["id"] for p in (or_cfg.get("presets") or []) if p.get("id")}
        if preset_id not in presets:
            return jsonify({
                "reason":  "unknown_preset",
                "message": f"preset_id={preset_id} 不存在",
            }), 400
        new_active = dict(or_cfg.get("active") or {})
        new_active[role] = preset_id
        save_config({"openrouter": {**or_cfg, "active": new_active}})
        # v1.0.1: pass openrouter.active so the reset matcher catches
        # this AND the llm_provider clause (analyzer reset). Pre-fix
        # ``["llm_provider"]`` worked by coincidence because the OR
        # active swap also affects the analyzer's deep/quick model
        # bindings; making the path explicit here documents that.
        _reset_config_dependent_singletons(["openrouter.active", "llm_provider"])
        return jsonify({"active": new_active})

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
            uid = g.user.id if g.user else None
            task = tm.submit("screen_v2", params, created_by=uid)
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
            uid = g.user.id if g.user else None
            task = tm.submit("paper_trade", {"session_id": session_id}, created_by=uid)
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
        """Generate a paper-trade plan + planned_orders for the requesting user.

        Reads the user's per-user advice (NOT the shared ``advice_json``),
        feeds it into ``process_analysis``, and surfaces
        ``plan_id`` / ``num_orders`` / ``triggered`` so the UI can show
        "已生成 / 立即成交 / 待触发" instead of an opaque ``tracked_id``.
        """
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.json or {}
        analysis_id = data.get("analysis_id")
        if not analysis_id:
            return jsonify({"ok": False, "error": "analysis_id required"}), 400
        try:
            aid = int(analysis_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "analysis_id must be int"}), 400

        from stock_trading_system.portfolio.database import PortfolioDatabase
        from stock_trading_system.strategy.paper_trader import process_analysis
        db_path = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        pdb = PortfolioDatabase(db_path)
        ana = pdb.get_analysis_by_id(aid)
        if not ana:
            return jsonify({"ok": False, "error": "Analysis not found"}), 404

        user_advice = pdb.get_user_advice(g.user.id, aid) or {}
        store = _get_paper_store()
        current_price = None
        try:
            router = _get_data_router()
            if router:
                pd = router.get_price(ana["ticker"])
                if pd:
                    current_price = pd.get("last") or pd.get("close")
        except Exception as e:  # noqa: BLE001
            logger.warning("price lookup for /api/paper/track failed: %s", e)

        res = process_analysis(
            store,
            analysis_id=aid,
            ticker=ana["ticker"],
            analysis_date=ana.get("date") or "",
            signal=ana.get("signal", ""),
            advice=user_advice,
            current_price=current_price,
            user_id=g.user.id,
            analysis_blob={
                "trade_decision":    ana.get("trade_decision") or "",
                "risk_assessment":   ana.get("risk_assessment") or "",
                "investment_debate": ana.get("investment_debate") or "",
            },
        )
        if not res.get("ok"):
            return jsonify({
                "ok": False,
                "error": res.get("error", "process_analysis failed"),
            }), 500

        # Audit log: keep ``analysis_tracked`` writes so the existing
        # tracking timeline UI still has its history rows.
        try:
            from stock_trading_system.strategy.paper_trader import manual_track
            manual_track(
                store, analysis_id=aid, ticker=ana["ticker"],
                session_id=int(res["session_id"]),
                notes=data.get("notes"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("manual_track audit log failed: %s", e)

        return jsonify({
            "ok": True,
            "session_id": res.get("session_id"),
            "plan_id": res.get("plan_id"),
            "num_orders": res.get("num_orders", 0),
            "triggered": len(res.get("triggered") or []),
        })

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
        """List tickers with their plan / position summary.

        v1.16: collapsed from O(N) per-session round-trips down to 4
        aggregated queries via ``list_ticker_sessions_summary``.

        v1.21: results are now grouped by ``(user_id, ticker)`` so
        legacy duplicate paper-trade sessions for the same ticker
        collapse to a single card. ``session_ids`` exposes every
        sibling so the detail endpoint can fan out across them.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        uid = int(g.user.id)
        store = _get_paper_store()
        mode_arg = (request.args.get("mode") or "forward").lower()
        mode = mode_arg if mode_arg in {"forward", "replay"} else None
        summaries = store.list_ticker_sessions_summary(mode=mode, user_id=uid)
        out = []
        for s in summaries:
            last = s.get("last_daily_stat") or {}
            evt = s.get("latest_event") or {}
            sib_ids = s.get("session_ids") or [int(s["id"])]
            out.append({
                # ``id`` stays the canonical (earliest) session so old
                # deep-links still resolve. ``latest_session_id`` is the
                # newest sibling; ``session_ids`` lists all of them so
                # the detail page can merge data across them.
                "id": int(s["id"]),
                "session_ids": sib_ids,
                "latest_session_id": int(s.get("latest_session_id") or s["id"]),
                "ticker": s["ticker"],
                "status": s["status"],
                "start_date": s["start_date"],
                "last_eod": s.get("last_eod_date"),
                "current_signal": evt.get("new_signal"),
                "current_action": evt.get("action"),
                "total_value": float(last.get("total_value")) if last.get("total_value") is not None
                    else float(s["start_capital"]),
                "cum_pnl_pct": float(last.get("cum_pnl_pct") or 0),
                "position_shares": float(last.get("position_shares") or 0),
                "close_price": float(last["close_price"]) if last.get("close_price") else None,
                # ``num_events`` already summed across siblings inside
                # ``list_ticker_sessions_summary``. ``analysis_count`` is
                # the same number — strategy events are 1:1 with
                # analyses that produced a tracked plan.
                "num_events": int(s.get("num_events") or 0),
                "analysis_count": int(s.get("num_events") or 0),
                # Hit-rate intentionally null in the list view — see docstring.
                "hit_rate": None,
                "hit_pretty": "—",
                "sparkline": s.get("sparkline") or [],
                "active_plan_count": int(s.get("active_plan_count") or 0),
                "pending_orders_count": int(s.get("pending_orders_count") or 0),
                "triggered_orders_count": int(s.get("triggered_orders_count") or 0),
                "open_position_shares": float(s["open_position_shares"])
                    if s.get("open_position_shares") is not None else None,
                "last_skip_reason": s.get("last_skip_reason"),
                "latest_analysis_at": evt.get("event_date"),
            })
        return jsonify(out)

    @app.route("/api/paper/tickers/<ticker>")
    def api_paper_ticker_detail(ticker: str):
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        uid = g.user.id
        store = _get_paper_store()
        sess = store.find_session_by_ticker(ticker.upper(), user_id=uid)
        if not sess:
            return jsonify({"error": "No session for ticker"}), 404
        sid = int(sess["id"])
        # v1.21: aggregate across legacy duplicate sessions for the same
        # (user, ticker). Older accounts can have several rows in
        # ``paper_trade_sessions`` for one ticker; the list page now
        # collapses them, so the detail view must merge events / plans /
        # orders / trades / dailies across all sibling session ids too —
        # otherwise clicking the aggregated card showed only one
        # session's history.
        sib_ids = store.aggregate_ticker_session_ids(ticker.upper(), user_id=uid) \
                  or [sid]

        def _by_event(e: dict) -> tuple:
            return (str(e.get("event_date") or ""), int(e.get("id") or 0))

        events: list[dict] = []
        for s_id in sib_ids:
            events.extend(store.list_strategy_events(s_id))
        events.sort(key=_by_event, reverse=True)

        dailies: list[dict] = []
        for s_id in sib_ids:
            dailies.extend(store.list_daily_stats(s_id, limit=1000))
        # Dailies merged across siblings — collisions on date are rare
        # but if they occur prefer the highest-id session's row (most
        # recent activity).
        dailies.sort(key=lambda d: (str(d.get("date") or ""),
                                     int(d.get("session_id") or 0)))

        trades: list[dict] = []
        for s_id in sib_ids:
            trades.extend(store.list_trades(s_id, limit=500))
        trades.sort(key=lambda t: str(t.get("entry_date") or ""), reverse=True)

        # Active plan = pick the one from the latest sibling that has one.
        active_plan = None
        for s_id in reversed(sib_ids):
            ap = store.get_active_plan(s_id)
            if ap is not None:
                active_plan = ap
                break
        active_orders = (
            store.list_orders(plan_id=active_plan["id"]) if active_plan else []
        )

        # Plan history: union across siblings, newest first.
        all_plans: list[dict] = []
        for s_id in sib_ids:
            all_plans.extend(store.list_plans(s_id))
        all_plans.sort(key=lambda p: str(p.get("created_at") or ""), reverse=True)

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
                except Exception as e:  # noqa: BLE001
                    logger.warning("plan_history get_analysis_by_id failed: %s", e)
                    entry["trade_decision"] = ""
            plan_history.append(entry)
        latest = events[0] if events else None
        latest_advice = None
        latest_trade_decision = None
        if latest and latest.get("analysis_id"):
            analysis_id = int(latest["analysis_id"])
            try:
                ana = _db.get_analysis_by_id(analysis_id)
                if ana:
                    latest_trade_decision = ana.get("trade_decision") or ""
            except Exception as e:  # noqa: BLE001
                logger.warning("ticker_detail: get_analysis_by_id failed: %s", e)
            # latest_advice MUST come from this user's private row, never
            # the legacy advice_json on the shared analysis_history row.
            try:
                user_advice_row = _db.get_user_advice(uid, analysis_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("ticker_detail: get_user_advice failed: %s", e)
                user_advice_row = None
            if user_advice_row:
                latest_advice = {
                    "action":                  user_advice_row.get("action"),
                    "confidence":              user_advice_row.get("confidence"),
                    "suggested_position_pct":  user_advice_row.get("position_pct"),
                    "entry_price_low":         user_advice_row.get("entry_low"),
                    "entry_price_high":        user_advice_row.get("entry_high"),
                    "stop_loss":               user_advice_row.get("stop_loss"),
                    "take_profit":             user_advice_row.get("take_profit"),
                    "reasoning":               user_advice_row.get("reasoning") or "",
                    "risk_warning":            user_advice_row.get("risk_warning") or "",
                }
        return jsonify({
            "session": sess,
            "session_ids": sib_ids,
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
        # paper-trade v1.5: require login + scope to current user. Without
        # user_id, find_session_by_ticker may return another user's older
        # session for the same ticker → manual EOD updates the wrong row
        # and the calling user's detail page stays empty.
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        store = _get_paper_store()
        sess = store.find_session_by_ticker(ticker.upper(), user_id=g.user.id)
        if not sess:
            return jsonify({"ok": False, "error": "Not found"}), 404
        try:
            from stock_trading_system.strategy.paper_trader import DailyUpdater
            updater = DailyUpdater(get_config(), store)
            rows = updater.update_session(int(sess["id"]))
            return jsonify({
                "ok": True,
                "new_rows": len(rows),
                "session_id": int(sess["id"]),
            })
        except Exception as e:
            logger.error("Manual EOD failed for %s: %s", ticker, e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/paper/backfill", methods=["POST"])
    def api_paper_backfill():
        if g.user is None:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            tm = _get_task_manager()
            uid = g.user.id
            # Pass user_id in BOTH params (so the worker scopes advice
            # lookups to this user) and created_by (audit trail).
            task = tm.submit(
                "paper_backfill",
                {"user_id": uid},
                created_by=uid,
            )
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
        # Inject LLM provider/model into shared research task params for
        # cache dedup. Use the same per-provider resolver the analyzer uses
        # so cache keys are stable (``qwen:qwen-plus``) rather than the
        # legacy ``qwen:`` empty-model form.
        if task_type in ("analysis", "screen", "screen_v2", "screen_v3", "backtest"):
            from stock_trading_system.llm.router import resolve_active_model
            cfg = get_config()
            uid_for_resolve = g.user.id if g.user else None
            prov, mdl = resolve_active_model(cfg, user_id=uid_for_resolve)
            params.setdefault("_provider", prov)
            params.setdefault("_model", mdl or "")

        uid = g.user.id if g.user else None
        # Inject the requester id into params so workers (e.g. analysis) can
        # capture per-user provenance + per-user advice without each route
        # remembering. Underscore-prefixed key matches __task_id__ etc.
        if uid is not None:
            params.setdefault("__user_id__", uid)
        try:
            task = tm.submit(task_type, params, title=title, created_by=uid)
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to submit task")
            return jsonify({"error": str(e)}), 500
        return jsonify(task)

    VALID_TASK_SCOPES = {"mine", "shared_research", "all"}

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_list():
        tm = _get_task_manager()
        task_type = request.args.get("type")
        status = request.args.get("status")
        scope = (request.args.get("scope") or "mine").strip()
        # Reject unknown scopes — never silently fall through to "no filter".
        if scope not in VALID_TASK_SCOPES:
            scope = "mine"
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        uid = g.user.id if g.user else None
        # Only admin can see 'all'; everyone else is downgraded to shared_research.
        if scope == "all" and (not g.user or g.user.role != "admin"):
            scope = "shared_research"
        items = tm.list(task_type=task_type, status=status,
                        limit=limit, offset=offset,
                        created_by=uid, scope=scope)
        total = tm.count(task_type=task_type, status=status,
                         created_by=uid, scope=scope)
        return jsonify({
            "tasks": items,
            "items": items,  # backward compat
            "total": total,
            "limit": limit,
            "offset": offset,
            "scope": scope,
        })

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def api_task_detail(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        # Enforce ownership: shared_research types are readable by any logged-in
        # user; private types (paper_trade, alerts, batch_analysis, ...) are
        # owner-or-admin only. Sensitive params on shared tasks are masked
        # before returning so we don't leak per-user context (user_id, etc.).
        err = _check_task_ownership(task)
        if err:
            return err
        return jsonify(_sanitize_shared_task(task))

    def _result_ref_to_int(ref: str) -> int | None:
        """Extract the trailing integer from a `<table>:<id>` result_ref."""
        if not ref or ":" not in ref:
            return None
        try:
            return int(ref.rsplit(":", 1)[1])
        except (ValueError, TypeError):
            return None

    def _params_dict(task: dict) -> dict:
        """Decode params_json on a task row, returning {} for malformed rows."""
        try:
            raw = json.loads(task.get("params_json") or "{}")
            return raw if isinstance(raw, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    def _check_task_ownership(task, require_owner=False):
        """Check if current user can read/mutate a task. Returns error response or None.

        Rules (default-deny — only ``SHARED_TYPES`` is an allow-list):

            * If ``task.type in TaskStore.SHARED_TYPES`` → any logged-in user
              may read detail/result. Mutations still require owner/admin.
            * Otherwise (``PRIVATE_TYPES`` *and* anything not classified yet,
              e.g. ``qwen_fundamentals``, ``meta_evolution``, ``echo``,
              future task types we haven't added to either list) → only
              owner/admin may even read it.
            * ``require_owner=True`` (cancel/delete/retry) always requires
              owner/admin, regardless of the type's classification.
        """
        from stock_trading_system.tasks.task_store import TaskStore
        uid = str(g.user.id) if g.user else None
        is_admin = bool(g.user and g.user.role == "admin")
        owner = str(task.get("created_by", ""))
        ttype = task.get("type", "")
        is_shared = TaskStore.is_shared_type(ttype)
        is_owner = uid is not None and owner == uid
        if require_owner and not is_owner and not is_admin:
            return jsonify({"error": "forbidden", "message": "Not task owner"}), 403
        if not is_shared and not is_owner and not is_admin:
            return jsonify({"error": "forbidden", "message": "Private task"}), 403
        return None

    # Per-task-type whitelist of params keys that are safe to expose to other
    # users on shared research tasks. Anything else is stripped so we don't
    # leak user_id, internal flags, or per-user context.
    _SHARED_PARAMS_WHITELIST = {
        "analysis":  {"ticker", "date", "_provider", "_model"},
        "screen":    {"market", "strategy", "_provider", "_model"},
        "screen_v2": {"market", "strategy", "enabled_gurus", "nl_query",
                      "final_count", "max_universe", "_provider", "_model"},
        "screen_v3": {"market", "candidate_n", "gurus", "mode",
                      "with_roundtable", "nl_query", "_provider", "_model"},
        "backtest":  {"ticker", "strategy_id", "period",
                      "initial_capital", "params", "_provider", "_model"},
        "report":    {"type", "_provider", "_model"},
    }

    def _sanitize_shared_task(task: dict) -> dict:
        """Mask sensitive params on shared task detail when viewer is not the owner."""
        from stock_trading_system.tasks.task_store import TaskStore
        ttype = task.get("type", "")
        if not TaskStore.is_shared_type(ttype):
            return task
        uid = str(g.user.id) if g.user else None
        owner = str(task.get("created_by", ""))
        is_admin = bool(g.user and g.user.role == "admin")
        if owner == uid or is_admin:
            return task
        whitelist = _SHARED_PARAMS_WHITELIST.get(ttype)
        if whitelist is None:
            return task
        try:
            raw = json.loads(task.get("params_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return task
        if not isinstance(raw, dict):
            return task
        filtered = {k: v for k, v in raw.items() if k in whitelist}
        cleaned = dict(task)
        cleaned["params_json"] = json.dumps(filtered, ensure_ascii=False)
        return cleaned

    @app.route("/api/tasks/<task_id>/result", methods=["GET"])
    def api_task_result(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        err = _check_task_ownership(task)
        if err:
            return err
        if task["status"] != "success" or not task.get("result_ref"):
            return jsonify({"status": task["status"], "message": "Result not ready"}), 404
        result = tm.get_result(task_id)
        if result is None:
            return jsonify({"error": "Result unavailable"}), 404
        return jsonify({"task": task, "result": result})

    @app.route("/api/tasks/<task_id>/retry", methods=["POST"])
    def api_task_retry(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        err = _check_task_ownership(task, require_owner=True)
        if err:
            return err
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
        err = _check_task_ownership(task, require_owner=True)
        if err:
            return err
        if task["status"] not in ("pending", "running"):
            return jsonify({"error": f"Cannot cancel task in status '{task['status']}'"}), 409
        ok = tm.cancel(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/<task_id>", methods=["DELETE"])
    def api_task_delete(task_id):
        tm = _get_task_manager()
        task = tm.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        err = _check_task_ownership(task, require_owner=True)
        if err:
            return err
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

    @app.route("/api/screen/v3/history")
    def api_screen_v3_history():
        """Paginated list of the requesting user's past v3 runs.

        Query params:
            ``mode``  — repeatable; one of classic/agent/agent_rt
            ``market`` — repeatable; one of us/cn/hk
            ``limit`` / ``offset`` — pagination, capped at 200/0
            ``include_failed=true`` — also surface failed/cancelled runs

        Multi-tenant invariant: the SQL ``WHERE created_by = ?`` clause
        is non-optional. There is no admin-bypass — even an admin only
        sees their own screening history through this endpoint.
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        modes = request.args.getlist("mode") or None
        markets = request.args.getlist("market") or None
        include_failed = (
            (request.args.get("include_failed") or "").lower() == "true"
        )
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 200))
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            return jsonify({"error": "limit/offset must be int"}), 400
        items, total = _get_task_store().list_screen_v3_history(
            user_id=g.user.id,
            modes=tuple(modes) if modes else None,
            markets=tuple(markets) if markets else None,
            limit=limit, offset=offset, include_failed=include_failed,
        )
        return jsonify({
            "items": items, "total": total,
            "limit": limit, "offset": offset,
        })

    @app.route("/api/screen/v3/history/<task_id>")
    def api_screen_v3_history_one(task_id: str):
        """Single-row variant. Used by the form's prefill flow.

        Cross-user reads return 404 — we don't leak the existence of
        another user's task id (constant-time-ish, the DB lookup runs
        either way).
        """
        if g.user is None:
            return jsonify({"error": "unauthorized"}), 401
        row = _get_task_store().get_screen_v3_history_one(task_id, g.user.id)
        if not row:
            return jsonify({"error": "not_found"}), 404
        return jsonify(row)

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
        """Trigger a V3 screening task.

        Validates that at least one guru is selected — running the
        agent pipeline with zero gurus is the worst kind of silent
        failure (the result has no candidate scores and the UI shows
        an empty list with no explanation). 400 the caller instead.
        """
        from flask import g
        from stock_trading_system.llm.router import get_active_provider

        body = request.get_json(silent=True) or {}
        cfg = get_config()
        user_id = getattr(g, "user", None) and g.user.id
        provider = get_active_provider(cfg, user_id=user_id)

        gurus_in = body.get("gurus")
        gurus_clean = [
            str(g).strip() for g in (gurus_in or [])
            if g and str(g).strip()
        ] if isinstance(gurus_in, list) else []
        if not gurus_clean:
            return jsonify({
                "error": "gurus_required",
                "message": "至少选择 1 位大师",
            }), 400

        market = (body.get("market") or "us").strip().lower()
        if market not in ("us", "cn", "hk"):
            return jsonify({
                "error": "invalid_market",
                "message": "market must be one of us / cn / hk",
            }), 400

        params = {
            "nl_query": body.get("nl_query", ""),
            "market": market,
            "candidate_n": int(body.get("candidate_n", 20)),
            "gurus": gurus_clean,
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
            created_by=user_id,
        )
        return jsonify({"task_id": task["id"], "estimated": params})

    @app.route("/api/screen/v3/results/<task_or_result_id>")
    def api_screen_v3_result(task_or_result_id):
        """Return a V3 screening result.

        Frontend hits /screener-v3?result=<id>, where ``<id>`` is the
        ``task.id`` (UUID) returned by /trigger. We accept either:

        * a task UUID  → look up via TaskStore.get(), follow ``result_ref``;
        * a positive integer → fall back to ``screen_results_v2`` row id.

        Schema normalization (v1.16): different worker versions write the
        candidate list under different keys. We normalize to the canonical
        ``candidates: [{ticker, composite_score, signal, guru_scores}]``
        shape the React island consumes:

            * payload['candidates']                → kept as-is
            * payload['results']                   → renamed to candidates
            * candidate['final_score']             → composite_score
            * candidate['guru_signals'] (list)     → guru_scores (dict by guru)

        The original ``results`` / ``final_score`` / ``guru_signals`` fields
        are preserved on each candidate too so any client written against
        the old shape keeps rendering.

        Privacy: ``params`` is filtered through
        ``_SHARED_PARAMS_WHITELIST['screen_v3']`` for non-owner viewers so
        ``user_id`` / ``provider`` / other internals never leak.
        """
        try:
            store = _get_task_store()

            # 1) Task-UUID path: this is the only shape the V3 frontend ever
            #    produces today. result_ref can point to either
            #    ``screen_results_v2:N`` (when the worker chose to pre-persist)
            #    or ``task_results_generic:N`` (default for screen_v3).
            task = store.get(task_or_result_id)
            if task and task.get("result_ref"):
                ref = str(task["result_ref"])
                payload: dict | None = None
                if ref.startswith("screen_results_v2:"):
                    sid = _result_ref_to_int(ref)
                    if sid is not None:
                        v2 = store.get_screen_v2_result(sid)
                        if v2:
                            payload = v2.get("results") or {}
                else:
                    raw = store.load_result(ref)
                    payload = raw if isinstance(raw, dict) else None
                if payload is not None:
                    candidates_dto = _normalize_v3_candidates(payload)
                    response = {
                        "id": _result_ref_to_int(ref),
                        "task_id": task["id"],
                        "created_at": task.get("completed_at") or task.get("created_at"),
                        "params": _v3_params_for_viewer(task),
                        "candidates": candidates_dto,
                        "roundtable": _v3_roundtable_envelope(payload, candidates_dto),
                        "run_metadata": _v3_run_metadata(payload, task, candidates_dto),
                    }
                    # Pass through any extra fields the v3 pipeline produced.
                    for k, v in payload.items():
                        if k not in ("candidates", "results", "roundtable",
                                     "id", "task_id", "metrics", "mode",
                                     "selected_gurus", "gurus_used",
                                     "candidates_count"):
                            response.setdefault(k, v)
                    return jsonify(response)

            # 2) Bare integer path: legacy / direct v2 result lookup.
            if str(task_or_result_id).isdigit():
                v2 = store.get_screen_v2_result(int(task_or_result_id))
                if v2:
                    inner = v2.get("results") or {}
                    candidates_dto = _normalize_v3_candidates(inner)
                    response = {
                        "id": v2.get("id"),
                        "task_id": v2.get("task_id"),
                        "created_at": v2.get("created_at"),
                        "candidates": candidates_dto,
                        "roundtable": _v3_roundtable_envelope(inner, candidates_dto),
                        "run_metadata": _v3_run_metadata(inner, None, candidates_dto),
                    }
                    for k, v in inner.items():
                        if k not in ("candidates", "results", "roundtable",
                                     "id", "task_id", "metrics", "mode",
                                     "selected_gurus", "gurus_used",
                                     "candidates_count"):
                            response.setdefault(k, v)
                    return jsonify(response)

            return jsonify({"error": "result_not_found"}), 404
        except Exception as e:  # noqa: BLE001
            logger.exception("V3 result lookup failed")
            return jsonify({"error": str(e)}), 500

    def _v3_roundtable_envelope(payload: dict, candidates: list[dict]) -> dict | None:
        """Project roundtable data into the ``{items: [...]}`` shape the
        React grid expects.

        Two source paths to support:

        1. Legacy: the worker pre-aggregated and emitted a top-level
           ``payload['roundtable']`` dict (rare — most v1 paths leave it
           NULL because per-ticker roundtable was per-candidate).
        2. v1.2 default: each candidate carries its own ``roundtable``
           dict (RoundtableResult.to_dict()) at ``candidate['roundtable']``.
           We collect those into a single envelope so the frontend can
           render the "Top 5 圆桌辩论" grid without re-walking candidates.
        """
        # Prefer an explicit top-level envelope if the worker already
        # built one (preserves any extra summary fields the legacy
        # roundtable codepath may have set).
        rt = payload.get("roundtable")
        if isinstance(rt, dict) and ("items" in rt or "summary" in rt):
            return rt
        items: list[dict] = []
        for c in candidates or []:
            ticker = c.get("ticker")
            crt = c.get("roundtable")
            if not (ticker and isinstance(crt, dict)
                    and isinstance(crt.get("debate_snippets"), list)):
                continue
            items.append({
                "ticker":           ticker,
                "consensus":        crt.get("consensus") or [],
                "dissent":          crt.get("dissent") or [],
                "split":            bool(crt.get("split")),
                "debate_snippets":  crt.get("debate_snippets") or [],
            })
        if not items:
            # Fall through to whatever the payload had (likely None) so
            # callers that already understand the envelope shape keep
            # rendering. We never invent an empty envelope.
            return rt if isinstance(rt, dict) else None
        return {"items": items}

    def _v3_run_metadata(payload: dict, task: dict | None,
                          candidates: list[dict]) -> dict:
        """Surface mode / LLM call counts / cache hit rate / gurus used
        for the result-page banner. Tolerates missing metrics so old
        rows still render (zeros / empty list rather than KeyError)."""
        metrics = payload.get("metrics") or {}
        # ``params_json`` on the task row is a JSON string; parse defensively.
        task_params: dict = {}
        if task and task.get("params_json"):
            raw_params = task["params_json"]
            if isinstance(raw_params, dict):
                task_params = raw_params
            elif isinstance(raw_params, str):
                try:
                    parsed = json.loads(raw_params)
                    if isinstance(parsed, dict):
                        task_params = parsed
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("v3 params_json parse failed: %s", e)
        # ``with_roundtable`` was either passed at submit time or implied
        # by ``mode == "agent_rt"``. Fall back to "any candidate has a
        # roundtable dict" for legacy results without metadata.
        explicit_mode = (
            payload.get("mode")
            or task_params.get("mode")
        )
        roundtable_enabled = bool(
            payload.get("roundtable_enabled")
            or task_params.get("with_roundtable")
            or any(
                isinstance(c.get("roundtable"), dict) for c in (candidates or [])
            )
            or explicit_mode == "agent_rt"
        )
        mode = explicit_mode or ("agent_rt" if roundtable_enabled else "agent")

        # Gurus: pipeline emits ``selected_gurus``; spec calls it
        # ``gurus_used``; user-submit can pass ``gurus``. Pick the first
        # truthy in priority order so legacy + new payloads both surface.
        gurus = (
            payload.get("gurus_used")
            or payload.get("selected_gurus")
            or task_params.get("gurus")
            or []
        )
        if not isinstance(gurus, list):
            gurus = []

        try:
            llm_calls = int(metrics.get("llm_calls", 0) or 0)
        except (TypeError, ValueError):
            llm_calls = 0
        try:
            cache_hits = int(metrics.get("cache_hits", 0) or 0)
        except (TypeError, ValueError):
            cache_hits = 0
        cache_hit_pct = round(cache_hits / llm_calls * 100) if llm_calls else 0
        try:
            duration_sec = int(metrics.get("duration_sec", 0) or 0)
        except (TypeError, ValueError):
            duration_sec = 0

        # v1.4 input-driven transparency — surface every dimension
        # used to BUILD the candidate pool (raw query, parsed
        # sectors/themes/keywords, structured criteria) AND every
        # filter that REJECTED candidates. UI uses this to render the
        # "input → constraints → source → filter" chain end to end.
        excluded_raw = payload.get("excluded_off_theme") or []
        excluded: list[dict] = []
        if isinstance(excluded_raw, list):
            for item in excluded_raw:
                if isinstance(item, dict):
                    t = (item.get("ticker") or "").strip()
                    if not t:
                        continue
                    excluded.append({
                        "ticker": t,
                        "sector": (item.get("sector") or "").strip(),
                        "reason": (item.get("reason") or "").strip(),
                    })
                elif isinstance(item, str) and item.strip():
                    # Backward compat: legacy rows persisted bare
                    # ticker strings before v1.4 added the structured
                    # shape — surface them with empty reason fields.
                    excluded.append({"ticker": item.strip(),
                                       "sector": "", "reason": ""})

        try:
            on_theme_count = int(payload.get("on_theme_count") or 0)
        except (TypeError, ValueError):
            on_theme_count = 0
        theme_meta = payload.get("theme_metadata")
        if not isinstance(theme_meta, dict):
            theme_meta = None

        # Pull parsed dimensions out of the persisted FilterSpec so
        # the front-end can show "解析出的行业 / 主题 / 关键词" without
        # re-running the parser.
        spec = payload.get("filter_spec") or {}
        if not isinstance(spec, dict):
            spec = {}
        parsed_sectors = spec.get("sectors") or []
        parsed_themes = spec.get("themes") or []
        parsed_keywords = spec.get("natural_fallback") or []
        intent_summary = spec.get("intent_summary") or ""
        raw_query = spec.get("raw_query") or task_params.get("nl_query") or ""

        return {
            "mode":                mode,
            "llm_calls":           llm_calls,
            "cache_hits":          cache_hits,
            "cache_hit_pct":       cache_hit_pct,
            "duration_sec":        duration_sec,
            "gurus_used":          [str(g) for g in gurus],
            "candidates_count":    int(payload.get("candidates_count")
                                        or len(candidates or [])),
            "roundtable_enabled":  roundtable_enabled,
            # v1.3/1.4 input-driven transparency
            "raw_query":           str(raw_query),
            "intent_summary":      str(intent_summary),
            "parsed_theme":        payload.get("parsed_theme"),
            "theme_metadata":      theme_meta,
            "parsed_sectors":      [str(x) for x in parsed_sectors if x],
            "parsed_themes":       [str(x) for x in parsed_themes if x],
            "parsed_keywords":     [str(x) for x in parsed_keywords if x],
            "universe_source":     payload.get("universe_source"),
            "on_theme_count":      on_theme_count,
            "excluded_off_theme":  excluded,
        }

    def _normalize_v3_candidates(payload: dict) -> list[dict]:
        """Project the worker-emitted payload into the canonical
        ``candidates`` list. Tolerates both the new ``candidates`` key and
        the legacy ``results`` key, and rewrites ``final_score`` →
        ``composite_score`` plus ``guru_signals`` (list) → ``guru_scores``
        (dict keyed by guru). Originals are kept intact too.

        v1.16 also backfills ``candidate.signal`` when the worker emitted
        it as null. Without this the dashboard summary card showed
        "看多 0 / 看空 0" for any non-null candidate list whose pipeline
        skipped the signal-aggregation step. Tier order:

            1. existing ``signal`` if non-empty
            2. majority among ``guru_scores``/``guru_signals`` votes
            3. ``composite_score`` band: >=65 bullish, <=40 bearish, else neutral
            4. ``"neutral"`` (last-resort default — never null in the response)
        """
        raw = payload.get("candidates")
        if not raw:
            raw = payload.get("results") or []
        out: list[dict] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if "composite_score" not in row and "final_score" in row:
                row["composite_score"] = row["final_score"]
            if "guru_scores" not in row:
                signals = row.get("guru_signals")
                if isinstance(signals, list):
                    row["guru_scores"] = {
                        s.get("guru"): s
                        for s in signals
                        if isinstance(s, dict) and s.get("guru")
                    }
                elif isinstance(signals, dict):
                    row["guru_scores"] = signals
            sig = row.get("signal")
            if not (isinstance(sig, str) and sig.strip()):
                row["signal"] = _derive_candidate_signal(row)
            out.append(row)
        return out

    def _derive_candidate_signal(row: dict) -> str:
        """Best-effort fallback for a candidate that lost its ``signal``
        field — see ``_normalize_v3_candidates`` docstring for the tier
        order. We always return a non-empty string so the React island's
        看多/看空 counters never silently roll back to 0 again.
        """
        guru_votes = []
        guru_scores = row.get("guru_scores")
        if isinstance(guru_scores, dict):
            for s in guru_scores.values():
                if isinstance(s, dict):
                    guru_votes.append((s.get("signal") or "").lower())
        else:
            for s in row.get("guru_signals") or []:
                if isinstance(s, dict):
                    guru_votes.append((s.get("signal") or "").lower())
        bullish = sum(1 for v in guru_votes
                      if "bull" in v or "buy" in v)
        bearish = sum(1 for v in guru_votes
                      if "bear" in v or "sell" in v)
        if bullish > bearish:
            return "bullish"
        if bearish > bullish:
            return "bearish"
        # No guru votes (or tied) — fall back to composite score band.
        score_raw = row.get("composite_score")
        if score_raw is None:
            score_raw = row.get("final_score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score >= 65:
                return "bullish"
            if score <= 40:
                return "bearish"
        return "neutral"

    def _v3_params_for_viewer(task: dict) -> dict:
        """Return ``params`` filtered for the requesting viewer.

        Owners and admins see every key; everyone else sees only the
        whitelist for ``screen_v3``. Strips ``user_id`` / ``__user_id__``
        / ``provider`` / future internal flags by default.
        """
        full = _params_dict(task)
        uid = str(g.user.id) if getattr(g, "user", None) else None
        owner = str(task.get("created_by", ""))
        is_admin = bool(getattr(g, "user", None) and g.user.role == "admin")
        if uid is not None and (uid == owner or is_admin):
            return full
        whitelist = _SHARED_PARAMS_WHITELIST.get("screen_v3") or set()
        return {k: v for k, v in full.items() if k in whitelist}

    # ── Seed Data ───────────────────────────────────────────────────────

    @app.route("/api/seed", methods=["POST"])
    @admin_required
    def api_seed():
        from stock_trading_system.web.seed_data import seed_msft_analysis
        seed_msft_analysis()
        return jsonify({"ok": True, "message": "MSFT mock data seeded"})

    # ── WebSocket Events ────────────────────────────────────────────────

    from flask_socketio import join_room

    @socketio.on("connect")
    def handle_connect():
        from flask import session as _sess
        # SocketIO connect doesn't go through before_request, so read session directly
        uid = _sess.get("user_id")
        if uid is None and _multi_tenant_ready:
            # Still allow connection — many events are useful pre-login
            # Just don't join a user room
            logger.info("WS connect: anonymous (no session)")
            return  # allow but no room
        if uid:
            # Verify user exists
            user = _user_repo.find_by_id(uid)
            if user:
                join_room(f"user:{user.id}")
                logger.info("Client connected → room user:%d", user.id)
            else:
                logger.info("WS connect: stale session uid=%d", uid)
        else:
            logger.info("Client connected (pre-migration mode)")

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("Client disconnected")

    # ── Catch-up API ────────────────────────────────────────────────────

    @app.route("/api/tasks/events")
    def api_task_events():
        """Return events for current user since given seq (for reconnect catch-up)."""
        from stock_trading_system.tasks.event_emitter import get_events_since
        user = getattr(g, "user", None)
        if not user:
            return jsonify({"error": "unauthorized"}), 401
        task_id = request.args.get("task_id", "")
        since = int(request.args.get("since", 0))
        db = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        events = get_events_since(db, task_id, user.id, since)
        return jsonify(events)

    @app.route("/api/tasks/running")
    def api_tasks_running():
        """Return currently running tasks for the logged-in user."""
        user = getattr(g, "user", None)
        if not user:
            return jsonify({"error": "unauthorized"}), 401
        import sqlite3 as _sql
        db = get_config().get("portfolio", {}).get("db_path", "data/portfolio.db")
        conn = _sql.connect(db)
        conn.row_factory = _sql.Row
        rows = conn.execute(
            "SELECT id, type, status, progress, created_at FROM tasks "
            "WHERE created_by = ? AND status IN ('pending','running') "
            "ORDER BY created_at DESC",
            (user.id,),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    return app


def run_app(host="0.0.0.0", port=5000, debug=False, config_path=None):
    """Create and run the web application."""
    app = create_app(config_path)
    logger.info("Starting web server on %s:%s", host, port)
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
