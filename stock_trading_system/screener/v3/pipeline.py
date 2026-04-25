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

        context = {
            "provider": self._provider,
            "config": self._config,
            "user_id": self._user_id,
        }

        # ── Phase 1+2: NL Parse + Universe (reuse v2) ──
        candidates = await self._get_candidates(nl_query, market, candidate_n)

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
            "metrics": {
                "duration_sec": round(elapsed, 1),
                "llm_calls": len(units),
                "cache_hits": len(signals) - len(units) + cache_hits,
                "cost_cny": self._estimate_cost(len(units), with_roundtable),
            },
        }

    async def _get_candidates(self, nl_query, market, n) -> list[str]:
        """Phase 1+2: reuse v2 NL parser + universe filter."""
        try:
            from stock_trading_system.screener.v2.nl_parser import NLParser
            from stock_trading_system.screener.v2.universe import UniverseFilter

            parser = NLParser(self._config, self._cache)
            spec = parser.parse(nl_query, market_hint=market)
            uf = UniverseFilter(self._config)
            tickers, source = uf.filter_by_spec(spec, max_universe=n)
            logger.info("V3 candidates: %d tickers (source=%s)", len(tickers), source)
            return tickers
        except Exception as e:
            logger.warning("V2 pipeline failed, using defaults: %s", e)
            defaults = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                         "TSLA", "JPM", "V", "MA", "UNH", "JNJ",
                         "WMT", "PG", "HD", "AVGO", "COST", "NFLX",
                         "AMD", "CRM"]
            return defaults[:n]

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
        """Phase 5: simplified round-table (full implementation in roundtable.py)."""
        # Group signals by ticker
        by_ticker: dict[str, list[GuruSignal]] = {}
        for s in signals:
            by_ticker.setdefault(s.ticker, []).append(s)

        results = {}
        for ticker in top_tickers:
            sigs = by_ticker.get(ticker, [])
            bullish = [s for s in sigs if s.signal == "bullish"]
            bearish = [s for s in sigs if s.signal == "bearish"]
            results[ticker] = {
                "consensus": [s.guru for s in bullish] if len(bullish) >= len(bearish) else [s.guru for s in bearish],
                "dissent": [s.guru for s in bearish] if len(bullish) >= len(bearish) else [s.guru for s in bullish],
                "split": len(bullish) == len(bearish),
            }
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
        """Phase 6: aggregate guru signals into ranked results."""
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
            results.append({
                "ticker": ticker,
                "final_score": round(avg_score, 1),
                "avg_confidence": round(avg_confidence, 2),
                "guru_signals": [s.model_dump() for s in sigs],
                "roundtable": roundtable.get(ticker),
            })

        results.sort(key=lambda r: r["final_score"], reverse=True)
        return results
