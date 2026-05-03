"""ScreenerV3Pipeline — 6-phase orchestration.

Phase 1: NL Parser (reuse v2)
Phase 2: Universe Filter (reuse v2)
Phase 3: Threshold Prefilter
Phase 4: Guru Agents Pool (parallel)
Phase 5: Round-table Debate (optional, Top 5)
Phase 6: Aggregator + Regime → Top K
"""

from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Any, Callable

from stock_trading_system.screener.v3.concurrency import run_guru_units
from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.pipeline")


def _summarise_price_history(df) -> dict:
    """Reduce a 6-month OHLCV frame to a small JSON-friendly summary.

    The guru prompts inject this verbatim; the goal is enough numerical
    context to back up a momentum / mean-reversion claim without
    flooding the LLM with 130 daily rows. Returns ``{}`` on missing
    data so the guru's data-coverage check can detect it.

    Fields:
        days:                number of bars seen
        last_close:          most recent close
        return_1m_pct:       21-bar return %
        return_3m_pct:       63-bar return %
        return_6m_pct:       126-bar return %
        sma200_distance_pct: (last - sma200) / sma200 * 100; null if <200 bars
        max_drawdown_pct:    peak-to-trough drawdown over the window
    """
    try:
        if df is None or len(df) == 0:
            return {}
        # Tolerate either pandas DataFrame (yfinance/akshare) or list-of-dicts.
        try:
            close = df["Close"]
        except Exception:
            try:
                close = df["close"]
            except Exception:
                return {}
        n = len(close)
        last = float(close.iloc[-1])
        out: dict = {
            "days":       n,
            "last_close": round(last, 4),
        }

        def _pct(window: int):
            if n <= window:
                return None
            prev = float(close.iloc[-window - 1])
            if prev == 0:
                return None
            return round((last / prev - 1) * 100, 2)

        out["return_1m_pct"] = _pct(21)
        out["return_3m_pct"] = _pct(63)
        out["return_6m_pct"] = _pct(125)

        if n >= 200:
            sma200 = float(close.tail(200).mean())
            if sma200 > 0:
                out["sma200_distance_pct"] = round(
                    (last - sma200) / sma200 * 100, 2,
                )
        else:
            out["sma200_distance_pct"] = None

        try:
            running_max = close.cummax()
            drawdown = (close - running_max) / running_max
            out["max_drawdown_pct"] = round(float(drawdown.min()) * 100, 2)
        except Exception:
            out["max_drawdown_pct"] = None
        return out
    except Exception:  # pragma: no cover — defensive
        return {}


# All 14 guru agent classes
_GURU_REGISTRY: dict[str, type] = {}


def _load_guru_registry() -> dict[str, type]:
    """Lazy-load all guru agent classes."""
    if _GURU_REGISTRY:
        return _GURU_REGISTRY

    from stock_trading_system.screener.v3.guru_agents.buffett import BuffettAgent
    from stock_trading_system.screener.v3.guru_agents.graham import GrahamAgent
    from stock_trading_system.screener.v3.guru_agents.munger import MungerAgent
    from stock_trading_system.screener.v3.guru_agents.lynch import LynchAgent
    from stock_trading_system.screener.v3.guru_agents.fisher import FisherAgent
    from stock_trading_system.screener.v3.guru_agents.burry import BurryAgent
    from stock_trading_system.screener.v3.guru_agents.ackman import AckmanAgent
    from stock_trading_system.screener.v3.guru_agents.wood import WoodAgent
    from stock_trading_system.screener.v3.guru_agents.druckenmiller import DruckenmillerAgent
    from stock_trading_system.screener.v3.guru_agents.damodaran import DamodaranAgent
    from stock_trading_system.screener.v3.guru_agents.pabrai import PabraiAgent
    from stock_trading_system.screener.v3.guru_agents.taleb import TalebAgent
    from stock_trading_system.screener.v3.guru_agents.marks import MarksAgent
    from stock_trading_system.screener.v3.guru_agents.dalio import DalioAgent

    for cls in [BuffettAgent, GrahamAgent, MungerAgent, LynchAgent, FisherAgent,
                BurryAgent, AckmanAgent, WoodAgent, DruckenmillerAgent,
                DamodaranAgent, PabraiAgent, TalebAgent, MarksAgent, DalioAgent]:
        _GURU_REGISTRY[cls.name] = cls
    return _GURU_REGISTRY


def get_all_guru_metas() -> list[dict]:
    """Return metadata for all 14 gurus (for frontend config panel)."""
    registry = _load_guru_registry()
    return [cls().to_meta() for cls in registry.values()]


class ScreenerV3Pipeline:
    """Orchestrate the 6-phase V3 screening pipeline."""

    def __init__(
        self,
        config: dict,
        user_id: int | None = None,
        provider: str = "qwen",
        local_cache: Any | None = None,
        on_progress: Callable | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        self._config = config
        self._user_id = user_id
        self._provider = provider
        self._cache = local_cache
        self._on_progress = on_progress
        self._cancel_check = cancel_check or (lambda: False)

    def _emit_stage(self, stage: str, phase: str, **extra: Any) -> None:
        """Emit a ``screen_v3_stage_start`` / ``screen_v3_stage_done`` event.

        Frontend ``ScreenerV3Progress`` consumes these to advance the V3
        stage timeline. Phase ∈ {"start", "done"}; ``extra`` carries
        per-stage metadata (count / total / source / tickers / signals).
        Failures swallowed so a broken progress sink can't kill the run.
        """
        if not self._on_progress:
            return
        evt_type = "screen_v3_stage_start" if phase == "start" else "screen_v3_stage_done"
        try:
            self._on_progress({"type": evt_type, "stage": stage, **extra})
        except Exception:
            pass

    async def run(
        self,
        nl_query: str = "",
        market: str = "us",
        candidate_n: int = 20,
        gurus: list[str] | None = None,
        mode: str = "agent",
        with_roundtable: bool = False,
        **kwargs,
    ) -> dict:
        """Execute the full pipeline. Returns results dict for persistence."""
        import time
        start_time = time.monotonic()

        registry = _load_guru_registry()
        selected_guru_names = gurus or ["buffett", "graham", "munger", "lynch"]
        selected_agents = [
            registry[g]() for g in selected_guru_names if g in registry
        ]

        # ── Phase 1+2: NL Parse + Universe (reuse v2) ──
        # Pull candidates first so the resolved FilterSpec / universe
        # source can be threaded into ``context`` for the guru agents
        # and roundtable. Without this, gurus would have to guess what
        # the user typed and the theme override clause never fires.
        self._emit_stage("parse", "start")
        self._emit_stage("universe", "start")
        candidates, filter_spec, universe_source = await self._get_candidates(
            nl_query, market, candidate_n,
        )
        self._emit_stage("parse", "done", count=len(candidates))
        self._emit_stage(
            "universe", "done",
            count=len(candidates), source=universe_source,
        )

        context = {
            "provider": self._provider,
            "config": self._config,
            "user_id": self._user_id,
            "nl_query": nl_query or "",
            "market": market,
            "filter_spec": filter_spec,
            "universe_source": universe_source,
        }

        if self._cancel_check():
            # Pre-guru cancel — no signals yet, RunStats fields all zero
            # but the payload contract is the same so the worker doesn't
            # need a special-case branch.
            from stock_trading_system.screener.v3.concurrency import RunStats as _RS
            return self._cancelled_payload(
                candidates=candidates,
                selected_guru_names=selected_guru_names,
                signals=[],
                universe_source=universe_source,
                filter_spec=filter_spec,
                run_stats=_RS(total_units=0, cache_hits=0, new_calls=0,
                              failed_units=0),
                with_roundtable=with_roundtable,
                start_time=start_time,
                phase="candidates",
            )

        # ── Phase 3: Threshold prefilter (optional) ──
        # V3 currently passes all candidates to guru agents
        # (prefiltering is implicit in universe selection)

        # ── Phase 4: Guru Agents Pool ──
        if mode == "classic":
            # Classic threshold mode — delegate to v2 gurus (zero change).
            # v1.4: classic now returns a real result dict via reuse of
            # the v2 threshold gurus, not an empty list.
            return await self._run_classic_mode(
                candidates, context,
                selected_guru_names=selected_guru_names,
                market=market,
                start_time=start_time,
                with_roundtable=with_roundtable,
                universe_source=universe_source,
                filter_spec=filter_spec,
            )

        # Build evaluation units: (guru, ticker, data_bundle)
        self._emit_stage("bundle", "start", total=len(candidates))
        bundles = await self._prepare_data_bundles(candidates, market)
        self._emit_stage("bundle", "done", total=len(bundles))
        units = [
            (guru, ticker, bundles[ticker])
            for ticker in candidates
            for guru in selected_agents
            if ticker in bundles
        ]
        self._emit_stage(
            "guru", "start",
            total=len(units),
            gurus=selected_guru_names,
            tickers=len(bundles),
        )

        async def _on_unit_start(guru, ticker):
            if self._on_progress:
                try:
                    self._on_progress({
                        "type": "guru_unit_start",
                        "guru": guru.name,
                        "guru_display": guru.display_name,
                        "ticker": ticker,
                    })
                except Exception:
                    pass

        async def _on_unit(guru, ticker, signal, cached, done, total):
            if self._on_progress:
                try:
                    self._on_progress({
                        "type": "guru_unit_done",
                        "guru": guru.name,
                        "guru_display": guru.display_name,
                        "ticker": ticker,
                        "signal": signal.signal,
                        "confidence": signal.confidence,
                        "reasoning_preview": signal.reasoning[:200],
                        "cached": cached,
                        "progress": done,
                        "total": total,
                    })
                except Exception:
                    pass

        async def _on_unit_failed(guru, ticker, error):
            if self._on_progress:
                try:
                    self._on_progress({
                        "type": "guru_unit_failed",
                        "guru": guru.name,
                        "guru_display": guru.display_name,
                        "ticker": ticker,
                        "error": str(error)[:200],
                    })
                except Exception:
                    pass

        signals, run_stats = await run_guru_units(
            units, context, self._cache,
            on_unit_start=_on_unit_start,
            on_unit_done=_on_unit,
            on_unit_failed=_on_unit_failed,
            cancel_check=self._cancel_check,
        )
        self._emit_stage(
            "guru", "done",
            total=run_stats.total_units,
            signals=len(signals),
            cache_hits=run_stats.cache_hits,
            new_calls=run_stats.new_calls,
            failed_units=run_stats.failed_units,
        )

        # Mid-pipeline cancel exit: skip roundtable + aggregate, return
        # the partial signals so the worker can persist them as a
        # cancelled-payload result_ref. We deliberately keep the
        # ``status`` field at the TOP-LEVEL key so existing callers (web
        # /api/screen/v3/results _v3_run_metadata) can detect the
        # partial state without inspecting every list element.
        if self._cancel_check():
            return self._cancelled_payload(
                candidates=candidates,
                selected_guru_names=selected_guru_names,
                signals=signals,
                universe_source=universe_source,
                filter_spec=filter_spec,
                run_stats=run_stats,
                with_roundtable=with_roundtable,
                start_time=start_time,
                phase="guru",
            )

        # ── Phase 5: Round-table (optional) ──
        roundtable_results: dict = {}
        roundtable_status = "skipped"
        if with_roundtable and not self._cancel_check():
            self._emit_stage(
                "roundtable", "start", tickers=len(candidates[:5]),
            )
            roundtable_results, roundtable_status = await self._run_roundtable(
                signals, candidates[:5], context,
            )
            self._emit_stage(
                "roundtable", "done",
                tickers=len(roundtable_results),
                status=roundtable_status,
            )

        # ── Phase 6: Aggregate + rank ──
        self._emit_stage("aggregate", "start")
        results = self._aggregate(candidates, signals, roundtable_results)
        self._emit_stage("aggregate", "done", results=len(results))
        if self._on_progress:
            try:
                self._on_progress({
                    "type": "aggregate_done",
                    "results_count": len(results),
                })
            except Exception:
                pass

        elapsed = time.monotonic() - start_time

        # Truthful metrics from RunStats — no more inferring cache hits
        # from a heuristic on fallback signal text. ``llm_calls`` kept
        # for backward compatibility with v1.2 ``run_metadata`` readers
        # but it now equals ``new_calls`` (real new LLM dispatches);
        # ``cache_hits`` and ``new_calls`` plus ``failed_units`` are the
        # canonical counters going forward.
        return {
            "engine": "v3",
            "mode": mode,
            "candidates_count": len(candidates),
            "selected_gurus": selected_guru_names,
            "results": results,
            "universe_source": universe_source,
            "filter_spec": filter_spec,
            "roundtable_status": roundtable_status,
            "metrics": {
                "duration_sec": round(elapsed, 1),
                "total_units": run_stats.total_units,
                "new_llm_calls": run_stats.new_calls,
                "llm_calls": run_stats.new_calls,  # legacy alias
                "cache_hits": run_stats.cache_hits,
                "failed_units": run_stats.failed_units,
                "cost_cny": self._estimate_cost(run_stats.new_calls, with_roundtable),
            },
        }

    def _cancelled_payload(
        self,
        *,
        candidates: list[str],
        selected_guru_names: list[str],
        signals: list,
        universe_source: str,
        filter_spec: dict,
        run_stats,
        with_roundtable: bool,
        start_time: float,
        phase: str,
    ) -> dict:
        """Build a partial-result payload for a cancelled run.

        The worker will persist this via ``TaskStore.save_result`` and
        then raise CancelledError so TaskManager marks the task as
        ``cancelled`` (not ``success``). Keeping the same shape as the
        success payload — minus a few late-stage fields — means the
        existing ResultsView can render the partial as a banner-tagged
        snapshot of "what we got before stop was pressed".
        """
        import time as _time
        elapsed = _time.monotonic() - start_time

        # Aggregate whatever signals we have so the partial UI still
        # shows ranked candidates (even if only a subset of guru/ticker
        # cells fired). _aggregate handles missing tickers gracefully.
        partial_results = self._aggregate(candidates, signals, {})

        return {
            "engine": "v3",
            "status": "cancelled",
            "partial": True,
            "cancelled_at_phase": phase,
            "candidates_count": len(candidates),
            "selected_gurus": selected_guru_names,
            "results": partial_results,
            "universe_source": universe_source,
            "filter_spec": filter_spec,
            "roundtable_status": "skipped",
            "metrics": {
                "duration_sec": round(elapsed, 1),
                "total_units": run_stats.total_units,
                "new_llm_calls": run_stats.new_calls,
                "llm_calls": run_stats.new_calls,
                "cache_hits": run_stats.cache_hits,
                "failed_units": run_stats.failed_units,
                "cost_cny": self._estimate_cost(
                    run_stats.new_calls, with_roundtable,
                ),
            },
        }

    async def _get_candidates(
        self, nl_query, market, n,
    ) -> tuple[list[str], dict, str]:
        """Phase 1+2: reuse v2 NL parser + universe filter.

        Returns ``(tickers, filter_spec_dict, universe_source)`` so the
        downstream guru / roundtable layer can show the user exactly
        what was screened on. ``filter_spec`` is the raw FilterSpec dict
        (intent_summary / sectors / themes / criteria / natural_fallback)
        — guru agents inject this into their LLM prompt verbatim, so a
        themed query never silently degenerates into pure financial
        analysis.

        Theme-aware fallback: when v2 throws on a themed query (storage,
        cloud-storage, ...), the storage_semiconductor / cloud_storage
        universes from ``UniverseFilter._THEME_FALLBACKS_US`` take
        priority over the broad mega-cap default list.
        """
        try:
            from stock_trading_system.screener.v2.nl_parser import NLParser
            from stock_trading_system.screener.v2.universe import UniverseFilter

            parser = NLParser(self._config, self._cache)
            spec = parser.parse(nl_query, market_hint=market)
            uf = UniverseFilter(self._config)
            tickers, source = uf.filter_by_spec(spec, max_universe=n)
            logger.info("V3 candidates: %d tickers (source=%s)", len(tickers), source)
            return tickers, spec.to_dict(), source
        except Exception as e:
            logger.warning("V2 pipeline failed, using defaults: %s", e)
            try:
                from stock_trading_system.screener.v2.universe import (
                    UniverseFilter as _UF,
                    _THEME_FALLBACKS_US,
                    _STORAGE_KEYWORDS,
                    _CLOUD_STORAGE_KEYWORDS,
                )

                q_lower = (nl_query or "").lower()
                if any(k in q_lower for k in _CLOUD_STORAGE_KEYWORDS):
                    on_theme = list(_THEME_FALLBACKS_US["cloud_storage"])
                    logger.info("V3 themed fallback: cloud_storage")
                    return on_theme[:n], {}, "theme_fallback"
                if any(k in q_lower for k in _STORAGE_KEYWORDS):
                    on_theme = list(_THEME_FALLBACKS_US["storage_semiconductor"])
                    logger.info("V3 themed fallback: storage_semiconductor")
                    return on_theme[:n], {}, "theme_fallback"
            except Exception:  # pragma: no cover — defensive
                pass

            defaults = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                         "TSLA", "AVGO", "COST", "NFLX",
                         "AMD", "CRM", "ORCL", "ADBE", "QCOM"]
            return defaults[:n], {}, "default"

    _BUNDLE_CONCURRENCY = 5

    async def _prepare_data_bundles(self, tickers, market) -> dict[str, dict]:
        """Prepare GuruDataBundle for each ticker (one-time I/O).

        Runs per-ticker fetches concurrently (semaphore-bounded), emits
        per-ticker progress, and honors cancel_check between tickers.
        Tickers that fail or are cancelled are dropped from the bundle map;
        the caller already filters units by `ticker in bundles`.
        """
        from stock_trading_system.data.data_router import DataRouter

        # Single shared router — avoids per-ticker construction and reuses cache/session.
        try:
            router = DataRouter(self._config, cache=self._cache)
        except Exception as e:
            logger.warning("DataRouter init failed, bundles will be empty: %s", e)
            router = None

        total = len(tickers)
        sem = asyncio.Semaphore(self._BUNDLE_CONCURRENCY)
        bundles: dict[str, dict] = {}
        done_count = 0

        def _fetch_one(t: str) -> dict:
            """Pull quote + fundamentals + recent news + price-history
            momentum + sector metadata for a ticker. Each sub-fetch is
            individually fault-tolerant — if news fails we still return
            what we got. Empty fields stay empty so the guru's prompt
            knows to emit a "数据不足" caveat instead of pretending."""
            if router is None:
                return {
                    "quote": {}, "fundamentals": {},
                    "news_recent": [], "price_history_summary": {},
                    "sector_industry": {},
                }
            try:
                quote = router.get_price(t) or {}
            except Exception:
                quote = {}
            try:
                fundamentals = router.get_fundamentals(t) or {}
            except Exception:
                fundamentals = {}
            try:
                # 5 fresh headlines is enough context for the news_check
                # SubAnalysis without bloating the prompt.
                news_recent = router.get_news(t, limit=5) or []
            except Exception:
                news_recent = []
            try:
                df = router.get_history_for_backtest(t, period="6mo", interval="1d")
            except Exception:
                df = None
            price_history_summary = _summarise_price_history(df)
            sector_industry = {
                "sector":   fundamentals.get("sector") or "",
                "industry": fundamentals.get("industry") or "",
            }
            return {
                "quote":                 quote,
                "fundamentals":          fundamentals,
                "news_recent":           news_recent,
                "price_history_summary": price_history_summary,
                "sector_industry":       sector_industry,
            }

        async def _one(t: str) -> tuple[str, dict] | None:
            nonlocal done_count
            if self._cancel_check():
                return None
            async with sem:
                if self._cancel_check():
                    return None
                data = await asyncio.to_thread(_fetch_one, t)
            done_count += 1
            if self._on_progress:
                try:
                    self._on_progress({
                        "type": "bundle_progress",
                        "ticker": t,
                        "done": done_count,
                        "total": total,
                    })
                except Exception:
                    pass
            return t, {
                "ticker": t,
                "market": market,
                "quote": data["quote"],
                "fundamentals_current": data["fundamentals"],
                # Historical fundamentals still empty — provider doesn't
                # expose them on a per-ticker basis. Guru prompts treat
                # an empty list as "no history snapshot available".
                "fundamentals_history": [],
                "news_recent":            data.get("news_recent", []),
                "price_history_summary":  data.get("price_history_summary", {}),
                "sector_industry":        data.get("sector_industry", {}),
            }

        results = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
        for r in results:
            if isinstance(r, tuple) and len(r) == 2:
                bundles[r[0]] = r[1]
        return bundles

    # ── Classic mode mapping ───────────────────────────────────────────
    #
    # V2 implements 4 threshold gurus (buffett/graham/lynch/oneil) as
    # heuristic scorers — no LLM. We reuse those agents for the V3
    # ``classic`` mode so users who pick "经典阈值" get real candidate
    # rankings, not an empty list.
    #
    # Mapping V3 selection (14 names) → V2 implementations (4 names):
    # only the intersection produces real scores. Names not in V2 are
    # silently dropped from classic mode (they're LLM-only by design).
    # The pipeline returns the V3 ``GuruSignal`` shape so the existing
    # ``_aggregate`` produces the canonical ``votes/consensus/...``
    # payload that ResultsView already renders.
    _V2_CLASSIC_MAP = {
        # V3 name : V2 build_gurus key
        "buffett": "buffett",
        "graham":  "graham",
        "lynch":   "lynch",
    }

    async def _run_classic_mode(
        self,
        candidates: list[str],
        context: dict,
        *,
        selected_guru_names: list[str],
        market: str,
        start_time: float,
        with_roundtable: bool,
        universe_source: str,
        filter_spec: dict,
    ) -> dict:
        """Real V2 threshold path — produces ranked candidates without LLM.

        Cancel-aware at every ticker boundary so a stop request during
        classic scoring (rare — it's fast) still honors the
        ``cancelled`` contract end-to-end.
        """
        import time
        from stock_trading_system.screener.v2.gurus import build_gurus
        from stock_trading_system.screener.v3.guru_agents.base import (
            GuruSignal, SubAnalysis,
        )

        self._emit_stage(
            "guru", "start",
            mode="classic",
            tickers=len(candidates),
            gurus=selected_guru_names,
        )

        v2_gurus = build_gurus(
            self._config,
            enabled=[
                self._V2_CLASSIC_MAP[g]
                for g in selected_guru_names
                if g in self._V2_CLASSIC_MAP
            ],
        )

        if not v2_gurus:
            # User picked only LLM-only gurus (e.g. fisher / burry) for
            # classic mode. Fail loudly rather than returning empty.
            self._emit_stage("guru", "done", total=0, signals=0)
            self._emit_stage("aggregate", "done", results=0)
            return {
                "engine": "v3",
                "mode": "classic",
                "candidates_count": len(candidates),
                "selected_gurus": selected_guru_names,
                "results": [],
                "universe_source": universe_source,
                "filter_spec": filter_spec,
                "roundtable_status": "skipped",
                "metrics": {
                    "duration_sec": round(time.monotonic() - start_time, 1),
                    "total_units": 0,
                    "new_llm_calls": 0,
                    "llm_calls": 0,
                    "cache_hits": 0,
                    "failed_units": 0,
                    "cost_cny": 0.0,
                    "classic_unsupported_gurus": [
                        g for g in selected_guru_names
                        if g not in self._V2_CLASSIC_MAP
                    ],
                },
            }

        # V2 gurus need fundamentals only (no quote/history/news).
        # Reuse our existing data bundle helper so we get the same
        # fundamentals snapshot the agent path uses.
        self._emit_stage("bundle", "start", total=len(candidates))
        bundles = await self._prepare_data_bundles(candidates, market)
        self._emit_stage("bundle", "done", total=len(bundles))

        signals: list[GuruSignal] = []
        v2_context = {"regime_label": "neutral"}
        total_units = 0
        completed = 0
        failed_units = 0
        for ticker in candidates:
            if self._cancel_check():
                break
            bundle = bundles.get(ticker, {})
            fundamentals = bundle.get("fundamentals_current", {}) or {}
            for v3_name, v2_name in self._V2_CLASSIC_MAP.items():
                if v3_name not in selected_guru_names:
                    continue
                if v2_name not in v2_gurus:
                    continue
                guru = v2_gurus[v2_name]
                total_units += 1
                if self._on_progress:
                    try:
                        self._on_progress({
                            "type": "guru_unit_start",
                            "guru": v3_name,
                            "guru_display": getattr(guru, "display_name", v3_name),
                            "ticker": ticker,
                        })
                    except Exception:
                        pass
                try:
                    match = guru.evaluate(ticker, fundamentals, v2_context)
                except Exception as e:  # noqa: BLE001
                    failed_units += 1
                    logger.warning("V2 classic %s failed for %s: %s",
                                   v2_name, ticker, e)
                    if self._on_progress:
                        try:
                            self._on_progress({
                                "type": "guru_unit_failed",
                                "guru": v3_name, "ticker": ticker,
                                "error": str(e)[:200],
                            })
                        except Exception:
                            pass
                    continue
                signal = self._v2_match_to_v3_signal(
                    v3_name, ticker, match,
                )
                signals.append(signal)
                completed += 1
                if self._on_progress:
                    try:
                        self._on_progress({
                            "type": "guru_unit_done",
                            "guru": v3_name,
                            "guru_display": getattr(guru, "display_name", v3_name),
                            "ticker": ticker,
                            "signal": signal.signal,
                            "confidence": signal.confidence,
                            "reasoning_preview": signal.reasoning[:200],
                            "cached": False,
                            "progress": completed,
                            "total": total_units,
                        })
                    except Exception:
                        pass

        self._emit_stage(
            "guru", "done", total=total_units, signals=len(signals),
            cache_hits=0, new_calls=0, failed_units=failed_units,
        )

        # Cancel may have stopped us mid-loop — return partial dict via
        # the same helper so worker treats it identically to agent-mode
        # cancel. RunStats with no LLM activity but the unit count we
        # actually got through.
        from stock_trading_system.screener.v3.concurrency import RunStats as _RS
        run_stats = _RS(
            total_units=total_units, cache_hits=0,
            new_calls=0, failed_units=failed_units,
        )
        if self._cancel_check():
            return self._cancelled_payload(
                candidates=candidates,
                selected_guru_names=selected_guru_names,
                signals=signals,
                universe_source=universe_source,
                filter_spec=filter_spec,
                run_stats=run_stats,
                with_roundtable=with_roundtable,
                start_time=start_time,
                phase="classic",
            )

        self._emit_stage("aggregate", "start")
        results = self._aggregate(candidates, signals, {})
        self._emit_stage("aggregate", "done", results=len(results))
        if self._on_progress:
            try:
                self._on_progress({
                    "type": "aggregate_done",
                    "results_count": len(results),
                })
            except Exception:
                pass

        elapsed = time.monotonic() - start_time
        return {
            "engine": "v3",
            "mode": "classic",
            "candidates_count": len(candidates),
            "selected_gurus": selected_guru_names,
            "results": results,
            "universe_source": universe_source,
            "filter_spec": filter_spec,
            "roundtable_status": "skipped",
            "metrics": {
                "duration_sec": round(elapsed, 1),
                "total_units": total_units,
                "new_llm_calls": 0,
                "llm_calls": 0,
                "cache_hits": 0,
                "failed_units": failed_units,
                "cost_cny": 0.0,
            },
        }

    @staticmethod
    def _v2_match_to_v3_signal(v3_name, ticker, match):
        """Convert V2 ``GuruMatch`` (match_pct 0–100 + fit + reason)
        to the V3 ``GuruSignal`` shape ``_aggregate`` consumes.

        Score band → V3 signal:
            >=70  ⇒ bullish (V2's own ``fit`` threshold)
            >=40  ⇒ neutral
            <40   ⇒ bearish

        ``confidence`` = match_pct / 100 (V2 already produces 0–100).
        """
        from stock_trading_system.screener.v3.guru_agents.base import (
            GuruSignal, SubAnalysis,
        )
        pct = float(getattr(match, "match_pct", 0))
        if pct >= 70:
            sig = "bullish"
        elif pct >= 40:
            sig = "neutral"
        else:
            sig = "bearish"
        met = list(getattr(match, "principles_met", []) or [])
        unmet = list(getattr(match, "principles_unmet", []) or [])
        sub_analyses = []
        if met:
            sub_analyses.append(SubAnalysis(
                name="原则匹配", score=int(round(pct)),
                details="；".join(met[:5]),
            ))
        if unmet:
            sub_analyses.append(SubAnalysis(
                name="原则不符", score=0,
                details="；".join(unmet[:5]),
            ))
        return GuruSignal(
            guru=v3_name,
            ticker=ticker,
            signal=sig,
            confidence=round(pct / 100, 2),
            reasoning=getattr(match, "reason", "") or "",
            sub_analyses=sub_analyses,
            key_metrics={},
            total_score=round(pct, 1),
        )

    async def _run_roundtable(
        self, signals, top_tickers, context,
    ) -> tuple[dict, str]:
        """Phase 5: real roundtable using ``screener.v3.roundtable.run_roundtable``.

        v1.4 wiring: the inline stub (v1.0–v1.3) only emitted bull/bear
        groupings and never produced real debate snippets or the LLM
        judge verdict. This now delegates to the canonical roundtable
        implementation in ``screener/v3/roundtable.py`` — same module
        that ``test_phase5_roundtable.py`` already covers — passing a
        thin LLM closure derived from the active provider config.

        Returns ``(results_dict, status)`` where ``status`` is one of:
          * ``"success"`` — at least one ticker debate ran with the
            LLM judge OR the bull/bear champions resolved without it.
          * ``"fallback"`` — judge LLM construction failed entirely;
            fell back to the inline summary so the run still completes.
          * ``"skipped"`` — set by the caller when the user opted out.

        ``RoundtableResult`` dataclass shape is preserved verbatim so
        downstream ``_aggregate`` + ResultsView don't need changes.
        """
        from stock_trading_system.screener.v3.roundtable import (
            run_roundtable, RoundtableResult,
        )

        query = (context or {}).get("nl_query") or ""
        spec = (context or {}).get("filter_spec") or {}

        # Group signals by ticker — run_roundtable expects a dict.
        by_ticker: dict[str, list[GuruSignal]] = {}
        for s in signals:
            by_ticker.setdefault(s.ticker, []).append(s)
        # Restrict to the requested top tickers, preserving order.
        top_signals: dict[str, list[GuruSignal]] = {
            t: by_ticker.get(t, []) for t in top_tickers
        }

        # Build the judge LLM closure — same provider/config path the
        # guru agents use (BaseGuruAgent._get_chat_model). On any
        # construction failure, fall back to ``llm_call=None`` so the
        # debate still runs without a judge verdict (run_roundtable
        # tolerates that mode).
        judge_status = "success"
        llm_call = self._build_judge_llm_call(context)
        if llm_call is None:
            judge_status = "fallback"

        # Async progress bridge — run_roundtable's on_progress is sync;
        # we reuse the same emission shape pipeline already broadcasts.
        def _rt_on_progress(evt: dict):
            if not self._on_progress:
                return
            try:
                self._on_progress(evt)
            except Exception:
                pass

        try:
            raw_results = await run_roundtable(
                top_signals,
                llm_call=llm_call,
                on_progress=_rt_on_progress,
                query=query,
                spec=spec if isinstance(spec, dict) else {},
            )
        except Exception as e:  # noqa: BLE001 — defensive
            logger.warning("roundtable.run_roundtable failed: %s", e)
            return {}, "fallback"

        # Normalise to plain dicts (RoundtableResult instances) so
        # _aggregate's existing ``hasattr(rt_obj, "to_dict")`` path
        # picks them up unchanged.
        return raw_results, judge_status

    def _build_judge_llm_call(self, context):
        """Construct a thin ``llm_call(system, user) -> str`` closure
        backed by the active LangChain chat model.

        llm-fallback v1.0: uses :func:`build_resilient_chat` directly so
        the round-table judge + Round 3 bull-rebuttal LLM calls also
        get cross-provider fallback on rate limits. Returns ``None`` if
        the chat model can't be built (missing API key etc.) — the
        round-table then runs in fallback mode without a judge.
        """
        try:
            from stock_trading_system.llm.resilient_chat import (
                build_resilient_chat,
            )
            ctx = context or {}
            chat = build_resilient_chat(
                config=ctx.get("config", {}) or {},
                kind="quick",
                user_id=ctx.get("user_id"),
            )
        except Exception as e:  # noqa: BLE001
            logger.info("roundtable judge llm unavailable: %s", e)
            return None

        from langchain_core.messages import SystemMessage, HumanMessage

        def _call(system: str, user: str) -> str:
            # roundtable.run_roundtable already tolerates raises by
            # appending "评判失败 (e)" — propagate so it surfaces.
            resp = chat.invoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            return getattr(resp, "content", "") or ""

        return _call

    def _estimate_cost(self, guru_calls: int, with_roundtable: bool) -> float:
        """Post-hoc cost estimate based on actual LLM call count.

        Qwen/Gemini responses don't always expose usage, so we approximate
        using the same AVG token assumptions as the pre-run estimator.
        """
        from stock_trading_system.screener.v3.estimator import (
            AVG_TOKENS_IN, AVG_TOKENS_OUT, PROVIDER_PRICING,
        )
        rt_calls = 15 if with_roundtable else 0
        total_calls = guru_calls + rt_calls
        tokens_in = total_calls * AVG_TOKENS_IN
        tokens_out = total_calls * AVG_TOKENS_OUT
        pricing = PROVIDER_PRICING.get(self._provider, PROVIDER_PRICING["qwen"])
        cost_cny = (tokens_in * pricing["in"] + tokens_out * pricing["out"]) / 1000
        return round(cost_cny, 2)

    def _aggregate(self, candidates, signals, roundtable) -> list[dict]:
        """Phase 6: aggregate guru signals into ranked results.

        v1.2 additions (append-only — never mutate v1.0 fields):
        - ``signal``: majority verdict (bullish / bearish / neutral / split).
          Pre-v1.2 the candidate row left this NULL and the API DTO ran
          ``_derive_candidate_signal`` to backfill it from guru votes; now
          the pipeline does the work itself so the table column never
          shows "—" for a row that actually has guru signals.
        - ``votes``: counts per stance + total.
        - ``consensus``: unanimous / majority / split — drives the
          frontend "全员共识 / 多数派 / 对峙" Badge.
        - ``confidence_range``: min / max / avg of guru confidence.
        - ``top_bull_argument`` / ``top_bear_argument``: highest-confidence
          guru's reasoning excerpt (max 200 chars) per side, for the
          expanded-row "核心论据" surface.
        """
        from dataclasses import is_dataclass, asdict

        by_ticker: dict[str, list[GuruSignal]] = {}
        for s in signals:
            by_ticker.setdefault(s.ticker, []).append(s)

        results = []
        for ticker in candidates:
            sigs = by_ticker.get(ticker, [])
            if not sigs:
                continue
            avg_score = sum(s.total_score for s in sigs) / len(sigs)
            avg_confidence = sum(s.confidence for s in sigs) / len(sigs)

            # ── v1.4 verdict aggregation (corrected) ──────────────────
            #
            # Pre-v1.4: ``unanimous`` fired whenever a single signal
            # exceeded the sum of the other two — so 5 neutral + 1
            # bullish surfaced as "majority bullish" and 4 bullish + 4
            # bearish + 4 neutral surfaced as "majority bullish" via
            # the trailing ``elif n_bull > n_bear`` fallback. Neutral
            # was being treated as a vote against bullish/bearish.
            #
            # New rules (per design v1.4):
            #   * unanimous: top-vote count == total (single signal).
            #     Includes all-neutral.
            #   * split: max-vote count tied between two signals.
            #     Verdict reports the tied stance pair as "split"
            #     when bullish/bearish tie; ties involving neutral
            #     resolve to "neutral" + split for transparency.
            #   * majority: top vote strictly leads but isn't unanimous.
            #     Verdict carries the actually-leading signal — neutral
            #     may legitimately be the verdict.
            bullish = [s for s in sigs if s.signal == "bullish"]
            bearish = [s for s in sigs if s.signal == "bearish"]
            neutral = [s for s in sigs if s.signal == "neutral"]
            total = len(sigs)
            n_bull, n_bear, n_neu = len(bullish), len(bearish), len(neutral)

            tally = [
                ("bullish", n_bull),
                ("bearish", n_bear),
                ("neutral", n_neu),
            ]
            top_count = max(c for _, c in tally)
            leaders = [name for name, c in tally if c == top_count and c > 0]

            if top_count == total and len(leaders) == 1:
                verdict, consensus = leaders[0], "unanimous"
            elif top_count == 0:
                # No signals at all — defensive; aggregate's caller
                # already filters empty ticker rows out.
                verdict, consensus = "neutral", "unanimous"
            elif len(leaders) >= 2:
                # Tie between top two (or all three). Bullish/bearish
                # tie is the canonical "split" the UI highlights in
                # orange; bullish/bearish == 0 with neutral tied to
                # one side resolves to neutral + split so users see
                # both the verdict and the contention.
                if "bullish" in leaders and "bearish" in leaders:
                    verdict, consensus = "split", "split"
                else:
                    # Neutral tied with one of bullish/bearish — show
                    # the directional stance as verdict but flag split.
                    directional = next(
                        (l for l in leaders if l != "neutral"), "neutral",
                    )
                    verdict, consensus = directional, "split"
            else:
                # Strict majority — top stance leads but isn't unanimous.
                verdict, consensus = leaders[0], "majority"

            confs = [s.confidence for s in sigs]
            conf_min, conf_max = min(confs), max(confs)

            top_bull = max(bullish, key=lambda s: s.confidence) if bullish else None
            top_bear = max(bearish, key=lambda s: s.confidence) if bearish else None

            def _arg(sig):
                if sig is None:
                    return None
                return {
                    "guru": sig.guru,
                    "confidence": round(sig.confidence, 2),
                    "snippet": (sig.reasoning or "")[:200],
                }

            # ``RoundtableResult`` is a dataclass — JSON-encode it via
            # to_dict() (preferred) or asdict() so the worker's
            # ``json.dumps`` later doesn't crash on the dataclass instance.
            rt_obj = roundtable.get(ticker) if roundtable else None
            if rt_obj is None:
                rt_dict = None
            elif hasattr(rt_obj, "to_dict"):
                rt_dict = rt_obj.to_dict()
            elif is_dataclass(rt_obj):
                rt_dict = asdict(rt_obj)
            else:
                rt_dict = rt_obj

            results.append({
                "ticker": ticker,
                "final_score": round(avg_score, 1),
                "avg_confidence": round(avg_confidence, 2),
                "guru_signals": [s.model_dump() for s in sigs],
                "roundtable": rt_dict,
                # ── v1.2 additive fields ─────────────────────────────
                "signal": verdict,
                "votes": {
                    "bullish": n_bull, "bearish": n_bear,
                    "neutral": n_neu, "total": total,
                },
                "consensus": consensus,
                "confidence_range": {
                    "min": round(conf_min, 2),
                    "max": round(conf_max, 2),
                    "avg": round(avg_confidence, 2),
                },
                "top_bull_argument": _arg(top_bull),
                "top_bear_argument": _arg(top_bear),
            })

        results.sort(key=lambda r: r["final_score"], reverse=True)
        return results
