"""Task workers — bridge between TaskManager and business logic.

Each worker signature: fn(params: dict, progress_cb) -> result_dict.

Workers are registered with TaskManager by `register_workers(tm, getters)`.
`getters` is a small dependency bundle so tests can inject fakes.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from stock_trading_system.utils import get_logger
from stock_trading_system.utils.timez import now_local

logger = get_logger("tasks.workers")


# Progress callback signature: (percent, step_desc=None, partial=None) -> None
ProgressCb = Callable[..., None]


# ── Analysis worker ───────────────────────────────────────────────────────────


def make_analysis_worker(get_analyzer, get_strategy_engine, get_portfolio, get_router):
    """Factory that builds an analysis worker bound to the given getters."""

    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        import time as _time
        from stock_trading_system.config import get_config
        from stock_trading_system.portfolio.database import normalize_analysis_depth
        from stock_trading_system.agents.rendering.state_normalizer import (
            normalize_state_to_text,
        )

        t_start = _time.perf_counter()
        ticker = (params.get("ticker") or "").upper().strip()
        if not ticker:
            raise ValueError("Missing 'ticker' in params")
        date = params.get("date")
        if not date:
            from stock_trading_system.utils.helpers import today_str
            date = today_str()

        # v2.1 — single normalizer reads ``deep_analysis`` (canonical
        # boolean from the new UI Switch) first, falls back to the
        # legacy ``depth`` string. Returns standard|deep — never
        # ``quick`` — so storage / paper-trade replay can't carry the
        # deprecated state forward. ``deep_analysis`` is also surfaced
        # on the result for paper-trade / future consumers that prefer
        # the boolean form.
        _normalized = normalize_analysis_depth(params)
        depth = _normalized["depth"]
        deep_analysis = _normalized["deep_analysis"]

        progress_cb(5, "初始化分析管线")
        analyzer = get_analyzer()
        task_id = params.get("__task_id__", "")
        # The web layer injects __user_id__ at submit time so the per-user
        # advice writer downstream knows whose holdings snapshot to take.
        user_id = params.get("__user_id__")

        # Pipeline progress callback — emit events for real-time frontend updates
        from stock_trading_system.tasks.event_emitter import emit_event as _emit_ev

        def _analysis_progress(event: dict):
            if task_id:
                _emit_ev(task_id, "analysis_pipeline", {"ticker": ticker, **event})

        progress_cb(15, "启动 7 Agent 分析")
        # Adapter compatibility: older / fake analyzers don't accept the
        # ``progress_cb`` / ``depth`` / ``user_id`` kwargs. Try the
        # richest call first and degrade signature-by-signature so
        # legacy fakes still work.
        # v1.0.1: pass user_id so the analyzer's _init_graph resolves
        # the per-user provider (router honors user_settings.llm_provider)
        # and caches the graph under the user's scope.
        try:
            raw = analyzer.analyze(
                ticker, date,
                progress_cb=_analysis_progress, depth=depth, user_id=user_id,
            )
        except TypeError as e:
            msg = str(e)
            if "user_id" in msg:
                # Older analyzer without user_id support — fall through
                # to the previous signature ladder.
                try:
                    raw = analyzer.analyze(
                        ticker, date,
                        progress_cb=_analysis_progress, depth=depth,
                    )
                except TypeError as e2:
                    msg2 = str(e2)
                    if "depth" in msg2:
                        try:
                            raw = analyzer.analyze(
                                ticker, date, progress_cb=_analysis_progress,
                            )
                        except TypeError as e3:
                            if "progress_cb" in str(e3):
                                raw = analyzer.analyze(ticker, date)
                            else:
                                raise
                    elif "progress_cb" in msg2:
                        raw = analyzer.analyze(ticker, date)
                    else:
                        raise
            elif "depth" in msg:
                try:
                    raw = analyzer.analyze(
                        ticker, date, progress_cb=_analysis_progress,
                    )
                except TypeError as e2:
                    if "progress_cb" in str(e2):
                        raw = analyzer.analyze(ticker, date)
                    else:
                        raise
            elif "progress_cb" in msg:
                raw = analyzer.analyze(ticker, date)
            else:
                raise

        # When iteration is enabled, analyze() returns (AnalysisResult, final_state)
        final_state = None
        if isinstance(raw, tuple):
            result, final_state = raw
        else:
            result = raw

        progress_cb(85, "生成策略建议")
        advice, holdings_snapshot = _build_advice_with_snapshot(
            result, ticker, get_strategy_engine, get_portfolio, get_router,
            user_id=user_id,
        )

        progress_cb(98, "整理结果")
        cfg = get_config()
        provider, model = _resolve_active_provider_model(cfg, user_id)

        out: dict = {
            "ticker": ticker,
            "date": date,
            "signal": result.signal,
            "market_report": result.market_report,
            "sentiment_report": result.sentiment_report,
            "news_report": result.news_report,
            "fundamentals_report": result.fundamentals_report,
            # Normalize TradingAgents state dicts to Chinese-headed Markdown
            # before storage. Previously ``str(dict)`` produced the
            # ``"{'judge_decision': '...'}"`` Python repr that bled into the
            # detail page's "完整论述" panel and the user-facing markdown
            # fallback. Pure-string fields pass through unchanged.
            "investment_debate": normalize_state_to_text(
                result.investment_debate, kind="investment_debate",
            ),
            "risk_assessment": normalize_state_to_text(
                result.risk_assessment, kind="risk_debate",
            ),
            "trade_decision": normalize_state_to_text(
                result.trade_decision, kind="trade_decision",
            ),
            "model": model,
            "provider": provider,
            "config_hash": _hash_llm_config(cfg),
            "duration_sec": _time.perf_counter() - t_start,
            "task_id": task_id or None,
            "created_by": user_id,
            "depth": depth,            # standard | deep (canonical)
            "deep_analysis": deep_analysis,  # boolean alias for new UI
            # v1.19: best-effort structured-rendering blob serialized for
            # storage. Empty string when the analyzer skipped extraction
            # (extractor unavailable, error, or per-tab failures already
            # rendered as ``None`` inside the dict).
            #
            # v1.7 (2026-05-06): also persist the status state machine so
            # the API + UI can distinguish "partial" / "failed" / "empty"
            # without re-running the classifier on every read. The
            # post-save hook on the TaskManager surfaces non-success
            # statuses on the task envelope so the task center can show
            # "结构化摘要生成失败".
            **_rendering_outputs(getattr(result, "rendering", None), result),
        }
        if final_state is not None:
            try:
                out["_final_state_json"] = _serialize_final_state(final_state)
            except Exception as e:  # noqa: BLE001
                logger.warning("final_state serialization failed: %s", e)
        # Per-user advice — written to user_analysis_advice by the post-save
        # hook in TaskManager. ``_advice_payload`` is the canonical key the
        # hook reads; ``advice`` is kept at the top level purely for in-process
        # callers (tests, future async tasks) and is intentionally NOT
        # persisted into the shared ``analysis_history`` row — task_store
        # ignores it (see ``_save_analysis_result``).
        if advice is not None:
            advice_dict = (
                advice if isinstance(advice, dict)
                else getattr(advice, "__dict__", None) or {}
            )
            out["advice"] = advice_dict
            out["_advice_payload"] = {
                "advice": advice_dict,
                "holdings_snapshot": holdings_snapshot,
            }
        return out

    return worker


def _resolve_active_provider_model(cfg: dict, user_id) -> tuple[str | None, str | None]:
    """Thin wrapper over :func:`stock_trading_system.llm.router.resolve_active_model`.

    Kept for backward compatibility — every other caller now imports the
    canonical resolver directly.
    """
    try:
        from stock_trading_system.llm.router import resolve_active_model
        return resolve_active_model(cfg, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("active provider/model lookup failed: %s", e)
        return None, None


def _hash_llm_config(cfg: dict) -> str:
    """SHA-1 of the LLM-relevant slice of the config.

    The cache layer keys analysis results on (ticker, date, config_hash);
    rotating a key or switching models invalidates without manual nudging.
    """
    import hashlib
    payload = {
        "llm": cfg.get("llm") or {},
        "qwen_model": (cfg.get("qwen") or {}).get("model"),
        "qwen_base_url": (cfg.get("qwen") or {}).get("base_url"),
        "gemini_model": (cfg.get("gemini") or {}).get("model"),
        "gemini_deep": (cfg.get("gemini") or {}).get("deep_think_model"),
        "llm_provider": cfg.get("llm_provider"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _serialize_final_state(final_state) -> str:
    """Convert TradingAgents' final_state into a JSON-safe blob.

    The recorder downstream rebuilds it into whatever shape `record_analysis`
    needs; we only need round-trip preservation here.
    """
    try:
        return json.dumps(final_state, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        # final_state may have non-serializable nested fields — fall back
        # to its string form so we at least leave a trace.
        return json.dumps({"repr": repr(final_state)}, ensure_ascii=False)


def _serialize_rendering(rendering) -> str:
    """JSON-encode the per-tab rendering dict for storage.

    Best-effort: a missing / unserializable rendering returns ``""`` so the
    storage layer writes an empty cell rather than crashing the whole task.
    """
    if not rendering:
        return ""
    try:
        return json.dumps(rendering, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        logger.warning("rendering_json serialization failed: %s", e)
        return ""


def _rendering_outputs(rendering, result) -> dict:
    """v1.7 — bundle the 4 rendering-status fields the worker needs to
    persist on the analysis_history row.

    ``result.rendering`` is the dict ``RenderingExtractor`` returned (may
    be empty / partial / fully populated). We also peek at the analyzer
    result to figure out which source reports actually had content, so
    a tab whose source markdown was empty is classified as ``empty``
    instead of ``failed``.
    """
    from datetime import datetime as _dt
    from stock_trading_system.agents.rendering.status import classify

    # Source-tab presence — derived from analyzer fields. Empty / missing
    # source means we shouldn't blame the LLM if the tab is empty.
    source_present: list[str] = []
    if getattr(result, "market_report", "") or "":
        source_present.append("Market")
    if getattr(result, "sentiment_report", "") or "":
        source_present.append("Sentiment")
    if getattr(result, "news_report", "") or "":
        source_present.append("News")
    if getattr(result, "fundamentals_report", "") or "":
        source_present.append("Fundamentals")
    if getattr(result, "investment_debate", None):
        source_present.append("Investment Debate")
    if getattr(result, "risk_assessment", None):
        source_present.append("Risk Assessment")
    if getattr(result, "trade_decision", None):
        source_present.append("Decision")
    # Overview is always derivable when any other source is present.
    if source_present:
        source_present.append("summary")

    json_str = _serialize_rendering(rendering)
    status, error = classify(rendering, source_tabs_present=source_present)

    # Promote any analyzer-side failure reason. ``_maybe_extract_rendering``
    # stashes the exception on ``result.rendering_error`` when it caught
    # one — keep that wording verbatim so an operator can grep for it.
    explicit_err = getattr(result, "rendering_error", None)
    if explicit_err and isinstance(explicit_err, str):
        # Truncate aggressively — never carry report bodies into status.
        error = explicit_err[:240]
        if status == "success":
            # Sanity: explicit error implies extraction didn't fully
            # succeed. Demote to failed so the UI banner shows up.
            status = "failed"

    return {
        "rendering_json": json_str,
        "rendering_status": status,
        "rendering_error": error,
        "rendering_generated_at":
            _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_advice_with_snapshot(
    result, ticker, get_strategy_engine, get_portfolio, get_router,
    user_id: int | None = None,
) -> tuple[dict | None, str | None]:
    """Build per-user advice + capture the holdings snapshot at advice time.

    The snapshot is what user_analysis_advice.holdings_context_snapshot stores
    — needed so an audit trail can replay why a particular position-sizing
    recommendation was made later.

    ``user_id`` is required after hardening-iteration-v1 P1.3 — worker
    context has no Flask g.user, and PortfolioManager will now raise if
    called without a tenant id. When the caller can't determine which
    user owns the run, snapshot is an empty list rather than a cross-
    tenant aggregate.
    """
    try:
        engine = get_strategy_engine()
        portfolio = get_portfolio()
        holdings = portfolio.get_holdings(user_id=user_id) if user_id else []
        snapshot = json.dumps(
            [
                {
                    "ticker": h.get("ticker") if isinstance(h, dict) else getattr(h, "ticker", None),
                    "shares": h.get("shares") if isinstance(h, dict) else getattr(h, "shares", None),
                    "avg_cost": h.get("avg_cost") if isinstance(h, dict) else getattr(h, "avg_cost", None),
                }
                for h in holdings
            ],
            ensure_ascii=False,
        )
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
        }, snapshot
    except Exception as e:  # noqa: BLE001 — advice is best-effort
        logger.warning("Strategy advice failed for %s: %s", ticker, e)
        return None, None


def record_agent_scores_for_analysis(
    analysis_id: int,
    final_state,
    ticker: str,
    date: str,
    get_router,
    db_path: str,
) -> None:
    """Record per-agent scorecards against an *existing* analysis row.

    The previous version of this function called ``db.save_analysis(...)``
    inside the worker just to get an id, which then collided with the
    canonical row written by ``_save_analysis_result`` — every successful
    iterated analysis ended up double-recorded. The fix: this function is
    now invoked *after* the canonical row exists, and reuses its id.
    """
    try:
        from stock_trading_system.config import get_config
        from stock_trading_system.agents.iterative.config import load_iteration_config
        from stock_trading_system.agents.iterative.agent_scorer import AgentScorer

        cfg = get_config()
        iter_config = load_iteration_config(cfg.get("iteration", {}))
        if not iter_config.enabled:
            return

        price_at_call = None
        try:
            router = get_router()
            price_data = router.get_price(ticker) if router else None
            if price_data:
                price_at_call = price_data.get("last") or price_data.get("close")
        except Exception as e:  # noqa: BLE001 — price is optional context
            logger.warning("price_at_call lookup failed for %s: %s", ticker, e)

        scorer = AgentScorer(db_path, iter_config)
        scorer.record_analysis(analysis_id, ticker, date, final_state, price_at_call)
    except Exception as e:  # noqa: BLE001 — scoring must never break analysis save
        logger.warning("Agent score recording failed (non-fatal): %s", e)


def deserialize_final_state(blob: str):
    """Inverse of ``_serialize_final_state`` — best-effort JSON load."""
    try:
        return json.loads(blob)
    except (TypeError, ValueError):
        return None


def make_score_update_worker(get_router):
    """Factory for the daily agent score update worker.

    Runs: backfill_returns → compute metrics → update Darwinian weights.
    """
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        from stock_trading_system.config import get_config
        from stock_trading_system.agents.iterative.config import load_iteration_config
        from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
        from stock_trading_system.agents.iterative.darwinian import update_darwinian_weights

        cfg = get_config()
        iter_config = load_iteration_config(cfg.get("iteration", {}))
        if not iter_config.enabled:
            return {"status": "skipped", "reason": "iteration not enabled"}

        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        scorer = AgentScorer(db_path, iter_config)

        progress_cb(20, "回填价格数据")
        router = get_router()
        get_price = router.get_price if router else lambda t: None
        updated = scorer.backfill_returns(get_price)

        progress_cb(60, "计算 Agent 指标")
        metrics = scorer.get_all_agent_metrics()

        progress_cb(80, "更新 Darwinian 权重")
        weights = update_darwinian_weights(scorer, iter_config.darwinian)

        return {
            "status": "ok",
            "backfilled": updated,
            "metrics": metrics,
            "weights": weights,
        }

    return worker


def make_meta_evolution_worker():
    """Factory for the weekly meta agent evolution worker.

    Runs: find worst agent → generate improved prompt → create A/B sessions.
    Optionally settles mature A/B tests.
    """
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        from stock_trading_system.config import get_config
        from stock_trading_system.agents.iterative.config import load_iteration_config
        from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
        from stock_trading_system.agents.iterative.prompt_store import PromptStore
        from stock_trading_system.agents.iterative.meta_agent import MetaAgent

        cfg = get_config()
        iter_config = load_iteration_config(cfg.get("iteration", {}))
        if not iter_config.enabled or not iter_config.meta.enabled:
            return {"status": "skipped", "reason": "iteration or meta not enabled"}

        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        scorer = AgentScorer(db_path, iter_config)
        prompt_store = PromptStore(db_path)

        # Try to get session store for A/B testing
        session_store = None
        try:
            from stock_trading_system.strategy.paper_trader.session_store import SessionStore
            session_store = SessionStore(db_path)
        except Exception:
            pass

        meta = MetaAgent(
            scorer=scorer,
            prompt_store=prompt_store,
            config=iter_config,
            session_store=session_store,
        )

        action = params.get("action", "mutate")

        if action == "settle":
            progress_cb(30, "结算 A/B 测试")
            settlements = meta.settle_ab_tests()
            return {"status": "ok", "action": "settle", "settlements": settlements}

        # Default: run mutation
        progress_cb(30, "查找最差 Agent")
        progress_cb(50, "生成改进 Prompt")
        result = meta.run_weekly()

        # Also settle any mature tests
        progress_cb(80, "结算成熟的 A/B 测试")
        settlements = meta.settle_ab_tests()
        result["settlements"] = settlements

        return result

    return worker


def make_cleanup_task_events_worker():
    """Daily cleanup: delete task_events for tasks completed > 7 days ago."""
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        import sqlite3
        from stock_trading_system.config import get_config
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute(
                "DELETE FROM task_events WHERE task_id IN ("
                " SELECT id FROM tasks WHERE status IN ('success','failed','cancelled') "
                " AND completed_at < datetime('now','-7 days'))"
            )
            deleted = cur.rowcount
            conn.commit()
        except Exception:
            deleted = 0
        finally:
            conn.close()
        return {"deleted": deleted}
    return worker


def make_screen_v3_worker():
    """Factory for the V3 guru agent screening worker."""
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        import asyncio
        from stock_trading_system.config import get_config
        from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline

        cfg = get_config()
        user_id = params.get("user_id")
        # v1.0 (openrouter): default the provider from the router's
        # active resolution chain (env > user > yaml > auto-detect)
        # instead of hardcoding qwen. params['provider'] is still
        # honored when the caller set it explicitly (e.g. tests).
        from stock_trading_system.llm.router import get_active_provider
        provider = (
            params.get("provider")
            or get_active_provider(cfg, user_id=user_id)
        )

        # Use unified emit_event for all progress events
        from stock_trading_system.tasks.event_emitter import emit_event
        task_id = params.get("__task_id__", "")
        cancel_event = params.get("__cancel_event__")

        def _on_progress(event):
            evt_type = event.get("type", "")
            if evt_type == "bundle_progress":
                # Phase: per-ticker data prep (5–25%)
                done = event.get("done", 0)
                total = event.get("total", 1)
                pct = 5 + int(done / max(total, 1) * 20)
                progress_cb(pct, f"准备数据 {done}/{total}: {event.get('ticker','')}")
                emit_event(task_id, "bundle_progress", event, user_id=user_id)
            elif evt_type == "guru_unit_done":
                # Phase: guru evaluation (25–95%)
                done = event.get("progress", 0)
                total = event.get("total", 1)
                pct = 25 + int(done / max(total, 1) * 70)
                progress_cb(pct, f"{event.get('guru_display','')}: {event.get('ticker','')}")
                emit_event(task_id, "guru_unit_done", event, user_id=user_id)
            elif evt_type in ("roundtable_start", "roundtable_done"):
                emit_event(task_id, evt_type, event, user_id=user_id)

        try:
            from stock_trading_system.data.local_cache import LocalCache
            db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
            cache_path = db_path.replace("portfolio.db", "cache.db")
            local_cache = LocalCache(cache_path, config=cfg)
        except Exception:
            local_cache = None

        pipeline = ScreenerV3Pipeline(
            config=cfg,
            user_id=user_id,
            provider=provider,
            local_cache=local_cache,
            on_progress=_on_progress,
            cancel_check=(lambda: cancel_event.is_set()) if cancel_event else None,
        )

        progress_cb(5, "启动 V3 大师评估管线")
        result = asyncio.run(pipeline.run(**{
            k: v for k, v in params.items()
            if k not in ("user_id", "provider", "__task_id__", "__cancel_event__")
        }))
        progress_cb(98, "整理结果")
        return result

    return worker


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
        # P1.3: report generators are per-tenant; caller injects __user_id__.
        # 'stock' report is the only type that doesn't need user_id (it's
        # an analysis run for one ticker, independent of holdings).
        user_id = params.get("__user_id__")
        progress_cb(20, f"生成 {rtype} 报告")
        gen = get_report_gen()
        if rtype == "stock":
            if not ticker:
                raise ValueError("stock report requires a ticker")
            content = gen.stock_report(ticker.upper())
        else:
            if user_id is None:
                raise RuntimeError(
                    f"report worker: __user_id__ missing for type={rtype}"
                )
            if rtype == "daily":
                content = gen.daily_report(user_id=user_id)
            elif rtype == "weekly":
                content = gen.weekly_report(user_id=user_id)
            elif rtype == "monthly":
                content = gen.monthly_report(user_id=user_id)
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
    return now_local().strftime("%Y-%m-%d")


# ── Batch analysis (one-click all holdings) ──────────────────────────────────


def make_batch_analysis_worker(deps):
    """Sequentially analyze every holding. Emits per-ticker WS events."""

    analysis_worker_fn = make_analysis_worker(
        deps.get_analyzer, deps.get_strategy_engine,
        deps.get_portfolio, deps.get_router,
    )

    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        skip_hours = int(params.get("skip_recent_hours", 4))
        date = params.get("date") or _today_str()
        task_id = params.get("__task_id__", "")
        # P1.3: worker is in a thread, no Flask g.user — caller injects
        # __user_id__ at submit time. Without it PortfolioManager raises.
        user_id = params.get("__user_id__")
        if user_id is None:
            raise RuntimeError(
                "batch_analyze_holdings: __user_id__ missing in params "
                "(worker can't determine which tenant's holdings to scan)"
            )

        # 1. Get holdings (scoped to the submitting user)
        pm = deps.get_portfolio()
        holdings = pm.get_holdings(user_id=user_id)
        tickers = [h["ticker"] for h in holdings if h.get("shares", 0) > 0]

        if not tickers:
            return {"total": 0, "analyzed": 0, "succeeded": 0,
                    "failed": 0, "skipped": 0, "items": []}

        # 2. Check skip (recently analyzed)
        from stock_trading_system.portfolio.database import PortfolioDatabase
        from stock_trading_system.config import get_config
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)

        items = []
        to_analyze = []

        for ticker in tickers:
            if skip_hours > 0:
                recent = db.get_analysis_history(ticker=ticker, limit=1)
                if recent and _within_hours(recent[0].get("created_at", ""), skip_hours):
                    items.append({
                        "ticker": ticker,
                        "status": "skipped",
                        "reason": f"{skip_hours} 小时内已分析",
                        "last_analysis_id": recent[0].get("id"),
                        "last_signal": recent[0].get("signal"),
                    })
                    _emit_batch_item(deps, task_id, items[-1],
                                     len(items) - 1, len(tickers))
                    continue
            to_analyze.append(ticker)

        total = len(tickers)
        skipped = len(items)
        succeeded = 0
        failed = 0

        progress_cb(5, f"持仓 {total} 只，跳过 {skipped} 只，待分析 {len(to_analyze)} 只")

        # 3. Analyze sequentially
        for i, ticker in enumerate(to_analyze):
            progress_cb(_batch_pct(i, len(to_analyze)),
                        f"分析 {ticker} ({skipped + i + 1}/{total})")

            def sub_progress(pct, step=None, partial=None,
                             _i=i, _n=len(to_analyze)):
                batch_pct = _batch_pct(_i, _n, sub_pct=pct)
                progress_cb(batch_pct, f"{ticker}: {step or ''}")

            try:
                result = analysis_worker_fn(
                    {"ticker": ticker, "date": date, "__task_id__": task_id},
                    sub_progress,
                )
                advice = result.get("advice") or {}
                item = {
                    "ticker": ticker,
                    "status": "success",
                    "analysis_id": result.get("analysis_id"),
                    "signal": result.get("signal"),
                    "confidence": advice.get("confidence"),
                    "advice_action": advice.get("action"),
                }
                items.append(item)
                succeeded += 1
            except Exception as e:
                logger.warning("Batch analysis failed for %s: %s", ticker, e)
                items.append({"ticker": ticker, "status": "failed",
                              "error": str(e)})
                failed += 1

            _emit_batch_item(deps, task_id, items[-1],
                             skipped + i, total)

        progress_cb(99, f"完成：{succeeded} 成功，{failed} 失败，{skipped} 跳过")

        return {
            "total": total,
            "analyzed": len(to_analyze),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "items": items,
        }

    return worker


def _emit_batch_item(deps, batch_task_id: str, item: dict,
                      index: int, total: int) -> None:
    from stock_trading_system.tasks.event_emitter import emit_event
    emit_event(batch_task_id, "batch_analysis_item", {
        "batch_task_id": batch_task_id,
        **item,
        "index": index,
        "total": total,
    })


def _batch_pct(i: int, n: int, sub_pct: float = 0) -> int:
    if n == 0:
        return 99
    per_ticker = 94.0 / n
    base = 5 + i * per_ticker
    return int(base + (sub_pct / 100) * per_ticker)


def _within_hours(created_at_str: str, hours: int) -> bool:
    from datetime import datetime, timedelta
    try:
        created = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        return now_local() - created < timedelta(hours=hours)
    except Exception:
        return False


# ── Echo (kept for smoke tests) ──────────────────────────────────────────────


def echo_worker(params: dict, progress_cb: ProgressCb) -> dict:
    progress_cb(10, "开始")
    progress_cb(50, "处理中")
    progress_cb(90, "即将完成")
    # Strip TaskManager-injected fields (e.g. __cancel_event__ — a threading.Event
    # which is not JSON-serializable) so the result can be persisted.
    safe_params = {k: v for k, v in params.items() if not str(k).startswith("__")}
    return {"echoed": safe_params}


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
        socketio: Any | None = None,
    ):
        self.get_analyzer = get_analyzer
        self.get_screener = get_screener
        self.get_report_gen = get_report_gen
        self.get_strategy_engine = get_strategy_engine
        self.get_portfolio = get_portfolio
        self.get_router = get_router
        self.socketio = socketio


def make_rendering_backfill_worker(get_analyzer):
    """Backfill ``rendering_json`` for analysis_history rows that don't
    have structured cards yet.

    Two modes:
        * ``params["analysis_id"]`` — single row retry (used by the
          "重新生成结构化摘要" button on the detail page).
        * ``params["limit"]`` — batch over rows where ``rendering_json``
          is empty / NULL OR ``rendering_status='failed'``, sorted
          newest first. Default limit is 10 to keep one task call
          bounded; users can re-submit for the next batch.

    Behaviour:
        * Re-uses ``RenderingExtractor`` against the saved per-tab text
          columns. Builds a lightweight result-shaped object so the
          extractor doesn't need the full analyzer pipeline.
        * Writes ``rendering_json / rendering_status / rendering_error
          / rendering_generated_at`` via ``database.update_rendering``.
        * Never touches ``signal``, ``advice_*``, paper-trade tables,
          or any other column. Strict storage isolation — backfill is
          purely a UI-data fixup.
        * Per-row failures are caught and logged; the task continues.

    Returns: ``{processed, succeeded, failed, partial, skipped, items: [...]}``.
    """
    def worker(params: dict, progress_cb: ProgressCb) -> dict:
        from datetime import datetime as _dt
        from stock_trading_system.config import get_config
        from stock_trading_system.portfolio.database import PortfolioDatabase
        from stock_trading_system.agents.rendering.extractor import (
            RenderingExtractor,
        )
        from stock_trading_system.agents.rendering.status import classify

        cfg = get_config()
        db_path = (cfg.get("portfolio") or {}).get("db_path", "data/portfolio.db")
        db = PortfolioDatabase(db_path)

        # ── Selection: single id OR batch ────────────────────────
        analysis_id = params.get("analysis_id")
        rows: list[dict]
        if analysis_id is not None:
            with db._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM analysis_history WHERE id = ?",
                    (int(analysis_id),),
                ).fetchone()
                rows = [dict(row)] if row else []
            mode_label = f"single id={analysis_id}"
        else:
            limit = max(1, min(int(params.get("limit") or 10), 50))
            with db._get_conn() as conn:
                rs = conn.execute(
                    """SELECT * FROM analysis_history
                          WHERE COALESCE(rendering_json, '') = ''
                             OR COALESCE(rendering_status, '') IN
                                  ('failed', 'pending', '')
                          ORDER BY id DESC
                          LIMIT ?""",
                    (limit,),
                ).fetchall()
                rows = [dict(r) for r in rs]
            mode_label = f"batch limit={limit}"

        progress_cb(5, f"扫描候选 ({mode_label})", stage="scan")

        if not rows:
            progress_cb(95, "没有待回填的行")
            return {"processed": 0, "succeeded": 0, "failed": 0,
                    "partial": 0, "skipped": 0, "items": []}

        # Reuse the main analyzer's quick LLM so the model + key path
        # match the live extraction. The analyzer initialises lazily on
        # first call so we don't pay startup cost when rows is empty.
        analyzer = get_analyzer()
        try:
            llm = analyzer._build_quick_llm()
            data_manager = analyzer._get_data_manager()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"backfill could not build LLM ({type(e).__name__}: {e})"
            )
        extractor = RenderingExtractor(llm, data_manager=data_manager)

        items: list[dict] = []
        succeeded = failed = partial = skipped = 0

        class _StubResult:
            """Minimal duck-type to feed RenderingExtractor without the
            full TradingAgents state. Field names mirror the analyzer's
            ``AnalysisResult`` dataclass (see analyzer.py)."""

        for idx, row in enumerate(rows, start=1):
            pct = 5 + int(round(idx / len(rows) * 90))
            ticker = (row.get("ticker") or "").upper()
            progress_cb(pct, f"提取 {ticker} ({idx}/{len(rows)})",
                         stage="extract")
            stub = _StubResult()
            stub.market_report = row.get("market_report") or ""
            stub.sentiment_report = row.get("sentiment_report") or ""
            stub.news_report = row.get("news_report") or ""
            stub.fundamentals_report = row.get("fundamentals_report") or ""
            stub.investment_debate = row.get("investment_debate") or ""
            stub.risk_assessment = row.get("risk_assessment") or ""
            stub.trade_decision = row.get("trade_decision") or ""

            # Skip rows whose source markdown is entirely empty —
            # nothing for the extractor to chew on. Mark as ``empty``
            # so the next backfill pass doesn't re-pick them.
            if not any([
                stub.market_report, stub.sentiment_report, stub.news_report,
                stub.fundamentals_report, stub.investment_debate,
                stub.risk_assessment, stub.trade_decision,
            ]):
                db.update_rendering(
                    int(row["id"]),
                    rendering_json="", status="empty",
                    error="no source reports to extract from",
                )
                skipped += 1
                items.append({"id": row["id"], "ticker": ticker,
                               "status": "empty", "reason": "no source"})
                continue

            try:
                rendering = extractor.extract(stub, ticker=ticker)
                json_str = json.dumps(rendering, ensure_ascii=False)
                # Use the same source-tab presence logic as the live
                # worker so partial classification matches.
                source_tabs = []
                for k, present in [
                    ("Market", stub.market_report),
                    ("Sentiment", stub.sentiment_report),
                    ("News", stub.news_report),
                    ("Fundamentals", stub.fundamentals_report),
                    ("Investment Debate", stub.investment_debate),
                    ("Risk Assessment", stub.risk_assessment),
                    ("Decision", stub.trade_decision),
                ]:
                    if present:
                        source_tabs.append(k)
                if source_tabs:
                    source_tabs.append("summary")
                status, err = classify(rendering, source_tabs_present=source_tabs)
                db.update_rendering(
                    int(row["id"]), rendering_json=json_str,
                    status=status, error=err,
                )
                if status == "success":
                    succeeded += 1
                elif status == "partial":
                    partial += 1
                else:
                    failed += 1
                items.append({"id": row["id"], "ticker": ticker,
                               "status": status, "reason": err})
            except Exception as e:  # noqa: BLE001
                err_msg = f"{type(e).__name__}: {e}"[:240]
                logger.warning(
                    "backfill row %s (%s) failed: %s",
                    row.get("id"), ticker, err_msg,
                )
                db.update_rendering(
                    int(row["id"]), rendering_json="", status="failed",
                    error=err_msg,
                )
                failed += 1
                items.append({"id": row["id"], "ticker": ticker,
                               "status": "failed", "reason": err_msg})

        progress_cb(95, "整理结果")
        return {
            "processed": len(rows),
            "succeeded": succeeded,
            "partial":   partial,
            "failed":    failed,
            "skipped":   skipped,
            "items":     items,
            "completed_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    return worker


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

    # ── Daily-snapshot backfill (dashboard "↻ 重新计算" button) ──
    tm.register("backfill_snapshots", make_backfill_snapshots_worker())

    if deps.get_report_gen:
        tm.register("report", make_report_worker(deps.get_report_gen))

    if deps.get_router:
        tm.register("qwen_fundamentals",
                    make_qwen_fundamentals_worker(deps.get_router))
        tm.register("qwen_news",
                    make_qwen_news_worker(deps.get_router))
        tm.register("backtest", make_backtest_worker(deps.get_router))

    # ── Batch analysis (one-click all holdings) ──
    if deps.get_analyzer and deps.get_strategy_engine and deps.get_portfolio \
            and deps.get_router:
        tm.register("batch_analysis", make_batch_analysis_worker(deps))

    # v1.7 — backfill structured rendering for older analysis_history
    # rows (or retry a single freshly-failed one). Re-uses the saved
    # tab text so it costs ~8 LLM calls per row but never re-runs the
    # main pipeline.
    if deps.get_analyzer:
        tm.register(
            "analysis_rendering_backfill",
            make_rendering_backfill_worker(deps.get_analyzer),
        )

    # ── Agent score update (daily backfill + Darwinian weights) ──
    if deps.get_router:
        tm.register("agent_score_update", make_score_update_worker(deps.get_router))

    # ── Meta Agent evolution (weekly prompt mutation + A/B settlement) ──
    tm.register("meta_evolution", make_meta_evolution_worker())

    # ── Screener V3 (Guru Agent deep evaluation) ──
    tm.register("screen_v3", make_screen_v3_worker())


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
    """Worker for paper-trade **replay backtest** sessions.

    paper-trade v1.5 — Finding 10: this worker drives the LEGACY
    single-portfolio backtester ``PaperTradeSimulator``, which replays
    a full date range over the global ``analysis_history`` signal
    stream. It is intentionally NOT the same code path as forward
    tracking — that lives in ``event_executor.process_analysis`` +
    ``order_engine.evaluate_day`` + ``DailyUpdater`` and runs
    automatically after a fresh analysis (TaskManager
    ``_post_analysis_save``) or via ``/api/paper/track`` for manual
    user-scoped enrolment.

    Forward vs replay split:
      * **Forward (canonical)** — per-ticker session, multi-stage
        plan, EOD risk via DailyUpdater. Used for live decision
        tracking from `analysis_history` rows the user just produced.
      * **Replay (this worker)** — global portfolio backtester. Used
        for backtest-style "replay the last N days" runs against the
        full signal stream. ``/api/paper/sessions/<id>/run`` POSTs to
        this path.

    Lazily builds one PaperTradeSimulator per process. Result is
    stored directly on the session row by the simulator; we return
    a result_ref pointing back to the session.
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
            # Replay simulator runs over all historical analyses without a
            # per-user lens; opt into the legacy ``advice_json`` fallback so
            # pre-v1.13 rows continue to feed the backtest.
            signals = SignalLoader(db_path, allow_legacy_no_user=True)
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
    """V2: replay analysis_history → per-ticker sessions + daily stats.

    ``params['user_id']`` scopes the run to one user's private advice.
    Without it, only shared signal/trade_decision text drives the plan
    (legacy advice_json on the shared row is intentionally ignored).
    """
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
        uid = params.get("user_id") if isinstance(params, dict) else None
        try:
            uid = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            uid = None
        result = backfill_all(store, pdb, cfg,
                              progress_cb=progress_cb, user_id=uid)
        return result
    return worker


def make_backfill_snapshots_worker():
    """Replay transactions + yfinance into daily_snapshots for one user.

    Wraps the migration script's per-user entry point so the dashboard
    "↻ 重新计算" button can run it through the existing TaskManager event
    pipeline (progress + completion broadcast).

    params:
        user_id (int):  resolved from g.user.id at submit time
        from   (str):   "earliest" (default) — earliest transaction; or an
                        ISO date string to start later.
        force  (bool):  pass-through to the migration's --force semantics.
    """
    def worker(params, progress_cb):
        from datetime import datetime as _dt
        from stock_trading_system.config import get_config
        from stock_trading_system.migrations.backfill_daily_snapshots import (
            backfill_user, backfill_all_users,
        )
        cfg = get_config()
        db_path = cfg.get("portfolio", {}).get("db_path", "data/portfolio.db")
        user_id = params.get("user_id")
        force = bool(params.get("force", False))

        progress_cb(2, "解析交易日窗口")
        if user_id is None:
            # No logged-in user (CLI / cron) — fall back to all-users mode.
            results = backfill_all_users(
                db_path,
                force=force,
                progress_cb=lambda pct, step: progress_cb(int(pct), step),
            )
            progress_cb(100, "完成")
            return {"results": results, "ran_at": _dt.utcnow().isoformat() + "Z"}

        result = backfill_user(
            db_path, int(user_id),
            force=force,
            progress_cb=lambda pct, step: progress_cb(int(pct), step),
        )
        progress_cb(100, "完成")
        return result
    return worker
