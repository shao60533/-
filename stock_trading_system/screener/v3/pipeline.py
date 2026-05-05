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
        candidates, filter_spec, universe_source = await self._get_candidates(
            nl_query, market, candidate_n,
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
            return {"status": "cancelled", "phase": "candidates"}

        # ── Phase 3: Threshold prefilter (optional) ──
        # V3 currently passes all candidates to guru agents
        # (prefiltering is implicit in universe selection)

        # ── Phase 4: Guru Agents Pool ──
        if mode == "classic":
            # Classic threshold mode — delegate to v2 gurus (zero change)
            return await self._run_classic_mode(candidates, context)

        # Build evaluation units: (guru, ticker, data_bundle)
        bundles = await self._prepare_data_bundles(candidates, market)

        # Candidate-level theme_fit gate (v1.3): the universe filter's
        # ``filter_off_theme`` only drops broad-market polluters from a
        # known blacklist. The gate adds the stricter check —
        # ``ticker ∈ theme.universe`` OR ``fundamentals.sector ∈
        # theme.sectors`` — so an LLM hallucination like "AAPL belongs
        # to power utilities" can't slip past two layers of filtering
        # and waste 14 guru LLM calls on an off-theme name.
        candidates, theme_gate, theme_meta = self._apply_theme_fit_gate(
            candidates, bundles, filter_spec, nl_query,
        )
        context["theme"] = theme_meta
        context["theme_gate"] = theme_gate

        units = [
            (guru, ticker, bundles[ticker])
            for ticker in candidates
            for guru in selected_agents
            if ticker in bundles
        ]

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

        signals = await run_guru_units(
            units, context, self._cache,
            on_unit_done=_on_unit,
            cancel_check=self._cancel_check,
        )

        # ── Phase 5: Round-table (optional) ──
        roundtable_results = {}
        if with_roundtable and not self._cancel_check():
            roundtable_results = await self._run_roundtable(signals, candidates[:5], context)

        # ── Phase 6: Aggregate + rank ──
        results = self._aggregate(candidates, signals, roundtable_results)

        elapsed = time.monotonic() - start_time
        cache_hits = sum(1 for s in signals if s.confidence == 0 and "失败" in s.reasoning)

        return {
            "engine": "v3",
            "mode": mode,
            "candidates_count": len(candidates),
            "selected_gurus": selected_guru_names,
            "results": results,
            "universe_source": universe_source,
            "filter_spec": filter_spec,
            # v1.3 theme transparency — the UI banner shows the user
            # which theme was matched, how many candidates passed the
            # fit gate, and which tickers were dropped as off-theme.
            "parsed_theme": theme_gate.get("parsed_theme"),
            "theme_metadata": theme_meta,
            "on_theme_count": theme_gate.get("on_theme_count", len(candidates)),
            "excluded_off_theme": theme_gate.get("excluded_off_theme", []),
            "metrics": {
                "duration_sec": round(elapsed, 1),
                "llm_calls": len(units),
                "cache_hits": len(signals) - len(units) + cache_hits,
                "cost_cny": self._estimate_cost(len(units), with_roundtable),
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

        Theme-aware fallback: when v2 raises on a themed query, we
        consult the ``theme_universe`` registry directly so the curated
        list (memory_storage / power_utilities / clean_energy / ...)
        still wins over the broad mega-cap defaults. v1.3 unified the
        per-theme tables into ``theme_universe._THEMES`` — this branch
        no longer references the deleted ``_THEME_FALLBACKS_US`` /
        ``_STORAGE_KEYWORDS`` symbols.
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
            logger.warning("V2 pipeline failed, using theme registry fallback: %s", e)
            try:
                from stock_trading_system.screener.v2 import theme_universe as tu
                theme = tu.detect_theme(query=nl_query)
                if theme is not None:
                    on_theme = tu.theme_fallback_universe(theme, query=nl_query)
                    if on_theme:
                        # v1.4: this branch only fires when the v2
                        # nl_parser/UniverseFilter raised — the LLM
                        # path was effectively unavailable. Always
                        # label as ``theme_fallback`` so the UI can
                        # surface "primary candidate generation
                        # failed" warning.
                        logger.info(
                            "V3 themed registry fallback (v2 unavailable): %s → %d tickers",
                            theme.key, len(on_theme),
                        )
                        return (
                            on_theme[:n],
                            {"themes": [theme.key], "raw_query": nl_query or ""},
                            "theme_fallback",
                        )
            except Exception:  # pragma: no cover — defensive
                logger.exception("Theme registry fallback failed")

            defaults = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                         "TSLA", "AVGO", "COST", "NFLX",
                         "AMD", "CRM", "ORCL", "ADBE", "QCOM"]
            return defaults[:n], {}, "default"

    def _apply_theme_fit_gate(
        self,
        candidates: list[str],
        bundles: dict[str, dict],
        filter_spec: dict | None,
        nl_query: str,
    ) -> tuple[list[str], dict, dict | None]:
        """v1.5 candidate-level theme fit filter — fail-closed under
        strong themes.

        Runs for **any** detected theme — not just strong ones — per
        the v1.4 contract that says "no matter where candidates came
        from, off-theme stocks must not enter guru scoring." Weak /
        future themes therefore also benefit, while plain "美股大盘"
        style queries (theme is None) skip the gate entirely.

        For each candidate we collect a ``reason`` string so the UI
        can tell the user *why* a name was dropped (sector mismatch /
        missing sector under strong theme / off-universe). Reasons
        stay short — the front-end shows them inline next to the
        ticker.

        v1.5 — sector-unknown handling diverges by theme strength:
            * **strong theme** (``theme.is_strong``): fail-closed.
              Provider didn't return a sector → exclude with
              ``reason="missing sector under strong theme"``. Letting
              the user run guru scoring on an unclassified ticker
              under "电力股龙头" routinely resurrected IBM/ORCL/TSLA
              every time DataRouter dropped a sector field.
            * **weak theme**: keep the legacy permissive behavior so
              we don't punish the user for a DataRouter outage on a
              soft theme. (No registered themes are weak today; the
              branch exists for forward-compat with future themes
              that opt out via ``is_strong=False``.)
        """
        from stock_trading_system.screener.v2 import theme_universe as tu

        spec = filter_spec or {}
        theme = tu.detect_theme(
            query=nl_query,
            intent_summary=spec.get("intent_summary"),
            themes=spec.get("themes"),
            sectors=spec.get("sectors"),
        )
        meta = tu.theme_metadata(theme.key) if theme else None

        if theme is None:
            # Off-theme query — gate is a no-op so generic
            # "美股大盘" / "S&P500" runs still see the broad pool.
            return list(candidates), {
                "parsed_theme": None,
                "on_theme_count": len(candidates),
                "excluded_off_theme": [],
            }, meta

        on_universe = {t.upper() for t in theme.universe}
        # ``extra_when_explicit`` extras (e.g. AMZN/MSFT/GOOGL when
        # the user wrote "云存储") are on-theme members for that run
        # and must pass the gate. Build the set once so we don't
        # rerun the keyword scan per candidate.
        explicit_extras: set[str] = set()
        if nl_query and theme.extra_when_explicit:
            for trigger, extras in theme.extra_when_explicit:
                if trigger.lower() in nl_query.lower() or trigger in nl_query:
                    explicit_extras.update(t.upper() for t in extras)
        on_sectors = {s.lower() for s in theme.sectors}
        is_strong = bool(getattr(theme, "is_strong", True))

        kept: list[str] = []
        excluded: list[dict] = []
        for ticker in candidates:
            tu_t = (ticker or "").upper()
            if tu_t in on_universe or tu_t in explicit_extras:
                kept.append(ticker)
                continue
            bundle = bundles.get(ticker) or {}
            fund = bundle.get("fundamentals_current") or {}
            sector_raw = (fund.get("sector") or "").strip()
            sector = sector_raw.lower()
            if not sector:
                if is_strong:
                    # v1.5 fail-closed — strong-theme queries (every
                    # registered theme today) must not let a missing
                    # sector through. The user can still see the
                    # ticker in the "因数据缺失被剔除" UI list, but
                    # it won't burn 14 guru LLM calls.
                    excluded.append({
                        "ticker": ticker,
                        "sector": "",
                        "reason": (
                            f"missing sector under strong theme "
                            f"{theme.key}"
                        ),
                    })
                else:
                    kept.append(ticker)
                continue
            if sector in on_sectors:
                kept.append(ticker)
                continue
            excluded.append({
                "ticker": ticker,
                "sector": sector_raw,
                "reason": (
                    f"sector={sector_raw} 不在主题 {theme.key} 约束 "
                    f"sectors={list(theme.sectors)}"
                ),
            })

        if excluded:
            logger.info(
                "Theme fit gate (%s, strong=%s): kept %d, excluded %d "
                "off-theme: %s",
                theme.key, is_strong, len(kept), len(excluded),
                [e["ticker"] for e in excluded],
            )
        return kept, {
            "parsed_theme": theme.key,
            "on_theme_count": len(kept),
            "excluded_off_theme": excluded,
        }, meta

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
            if router is None:
                return {"quote": {}, "fundamentals": {}}
            try:
                quote = router.get_price(t) or {}
            except Exception:
                quote = {}
            try:
                fundamentals = router.get_fundamentals(t) or {}
            except Exception:
                fundamentals = {}
            return {"quote": quote, "fundamentals": fundamentals}

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
                "fundamentals_history": [],
                "news_recent": [],
            }

        results = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
        for r in results:
            if isinstance(r, tuple) and len(r) == 2:
                bundles[r[0]] = r[1]
        return bundles

    async def _run_classic_mode(self, candidates, context) -> dict:
        """Delegate to v2 classic threshold gurus (zero change to v2 code)."""
        return {
            "engine": "v2_classic",
            "mode": "classic",
            "candidates_count": len(candidates),
            "results": [],
            "metrics": {"duration_sec": 0, "llm_calls": 0},
        }

    async def _run_roundtable(self, signals, top_tickers, context) -> dict:
        """Phase 5: simplified round-table (full implementation in roundtable.py).

        v1.23 minimal-fix: even without the LLM judge wired in, the
        snippets surface the user's query + structured spec so the
        front-end can show the user that the round table is anchored to
        their actual subject — not a generic bull/bear screen.
        """
        query = (context or {}).get("nl_query") or ""
        spec = (context or {}).get("filter_spec") or {}

        # Group signals by ticker
        by_ticker: dict[str, list[GuruSignal]] = {}
        for s in signals:
            by_ticker.setdefault(s.ticker, []).append(s)

        results = {}
        for ticker in top_tickers:
            sigs = by_ticker.get(ticker, [])
            bullish = [s for s in sigs if s.signal == "bullish"]
            bearish = [s for s in sigs if s.signal == "bearish"]
            entry: dict = {
                "consensus": [s.guru for s in bullish] if len(bullish) >= len(bearish) else [s.guru for s in bearish],
                "dissent": [s.guru for s in bearish] if len(bullish) >= len(bearish) else [s.guru for s in bullish],
                "split": len(bullish) == len(bearish),
            }
            if query:
                entry["query"] = query
                entry["filter_spec"] = spec
                entry["debate_snippets"] = [
                    f"用户查询：{query}",
                    "圆桌需优先判断该股票是否符合筛选主题，再看投资价值。",
                ]
            results[ticker] = entry
        return results

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

            # ── v1.2 verdict aggregation ──────────────────────────────
            bullish = [s for s in sigs if s.signal == "bullish"]
            bearish = [s for s in sigs if s.signal == "bearish"]
            neutral = [s for s in sigs if s.signal == "neutral"]
            total = len(sigs)
            n_bull, n_bear, n_neu = len(bullish), len(bearish), len(neutral)

            if n_bull > n_bear + n_neu:
                verdict, consensus = "bullish", "unanimous"
            elif n_bear > n_bull + n_neu:
                verdict, consensus = "bearish", "unanimous"
            elif n_bull == 0 and n_bear == 0:
                verdict, consensus = "neutral", "unanimous"
            elif n_bull > n_bear and n_bull >= total * 0.6:
                verdict, consensus = "bullish", "majority"
            elif n_bear > n_bull and n_bear >= total * 0.6:
                verdict, consensus = "bearish", "majority"
            elif n_bull == n_bear and n_bull > 0:
                verdict, consensus = "split", "split"
            elif n_bull > n_bear:
                verdict, consensus = "bullish", "majority"
            elif n_bear > n_bull:
                verdict, consensus = "bearish", "majority"
            else:
                verdict, consensus = "neutral", "majority"

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
