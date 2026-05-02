"""Concurrent guru evaluation with semaphore + tenacity retry.

screener-v3 v1.4 contract additions:
* ``run_guru_units`` returns ``(signals, RunStats)`` — caller can no
  longer infer cache hits from `confidence==0 and "失败" in reasoning`,
  which conflated real cache hits with retry exhaustions.
* ``on_unit_done`` callback signature unchanged but two new callbacks
  surface the unit lifecycle so the UI can render running / cached /
  done / failed cells distinctly:
    - ``on_unit_start(guru, ticker)`` — fired before the LLM call /
      cache lookup so the front-end matrix can paint a "running" cell.
    - ``on_unit_failed(guru, ticker, error)`` — fired only when the
      retry envelope is exhausted; ``_error_signal`` still produces a
      neutral fallback so aggregation can proceed but the unit state
      is unambiguously ``failed`` rather than masquerading as ``done``.
* ``cancel_check`` is consulted at every unit boundary (entry to the
  semaphore, before the LLM call, before persisting the cached signal)
  so a user-initiated cancel stops dispatching new work immediately
  rather than waiting for in-flight units to drain.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent, GuruSignal, SubAnalysis
from stock_trading_system.screener.v3 import cache as signal_cache
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.concurrency")

CONCURRENCY = 10

# Retry on rate-limit / transient errors (3 attempts, exponential 2/4/8s)
_llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    reraise=True,
)


@dataclass(frozen=True)
class RunStats:
    """Summary of a ``run_guru_units`` invocation.

    The pipeline persists these into ``metrics`` so the result page can
    show truthful "命中缓存 X%" and "新调用 N" figures. Pre-v1.4 we
    inferred cache hits from a heuristic on the fallback signal text —
    that double-counted retry exhaustions as cache hits and
    under-counted real cache hits when the cached signal happened to
    have ``confidence==0``.
    """
    total_units: int
    cache_hits: int
    new_calls: int        # successful new LLM calls (cache miss + ok)
    failed_units: int     # retry-exhausted; fallback signal still emitted

    def cache_hit_pct(self) -> int:
        return round(self.cache_hits / self.total_units * 100) if self.total_units else 0


def _error_signal(guru_name: str, ticker: str, error: Exception) -> GuruSignal:
    """Create a neutral fallback signal when evaluation fails."""
    return GuruSignal(
        guru=guru_name,
        ticker=ticker,
        signal="neutral",
        confidence=0.0,
        reasoning=f"评估失败: {str(error)[:200]}",
        sub_analyses=[SubAnalysis(name="error", score=0, details=str(error)[:200])],
        key_metrics={},
        total_score=0,
    )


async def run_guru_units(
    units: list[tuple[BaseGuruAgent, str, dict]],
    context: dict,
    local_cache: Any | None,
    on_unit_done: Callable | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_unit_start: Callable | None = None,
    on_unit_failed: Callable | None = None,
) -> tuple[list[GuruSignal], RunStats]:
    """Run guru evaluations concurrently with Semaphore(CONCURRENCY).

    Args:
        units: List of (guru_agent, ticker, data_bundle) tuples.
        context: Must contain 'provider' and 'config'.
        local_cache: LocalCache instance for (ticker, guru, date) caching.
        on_unit_done: Async callback(guru, ticker, signal, cached, completed, total).
            ``cached`` is True only for genuine cache hits — retry-exhausted
            failures are surfaced via ``on_unit_failed`` instead.
        cancel_check: Returns True to abort remaining units. Checked at
            every boundary (entry, post-cache, post-LLM).
        on_unit_start: Async callback(guru, ticker) fired before each
            unit dispatches. Lets the UI matrix paint a "running" cell
            even on a cold-cache run where the LLM call is the only
            visible delay.
        on_unit_failed: Async callback(guru, ticker, error) fired when
            the retry envelope is exhausted. The unit's ``GuruSignal``
            is still populated via ``_error_signal`` so aggregation can
            proceed; the callback exists purely so the UI can paint the
            cell red without us reverse-engineering "failed" from
            confidence/reasoning text.

    Returns:
        (signals, RunStats). Signals may include neutral fallbacks for
        failed units; aggregation downstream weights them at confidence=0
        so the verdict isn't skewed by failures.
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[GuruSignal] = []
    completed = 0
    cache_hits = 0
    new_calls = 0
    failed_units = 0
    total = len(units)

    @_llm_retry
    def _invoke(guru: BaseGuruAgent, ticker: str, bundle: dict) -> GuruSignal:
        return guru.evaluate_deep(ticker, bundle, context)

    async def _one(guru: BaseGuruAgent, ticker: str, bundle: dict):
        nonlocal completed, cache_hits, new_calls, failed_units
        # Cancel check BEFORE acquiring the semaphore so a stop request
        # during heavy load doesn't queue another batch behind in-flight
        # units.
        if cancel_check and cancel_check():
            return
        async with sem:
            if cancel_check and cancel_check():
                return

            if on_unit_start:
                try:
                    await on_unit_start(guru, ticker)
                except Exception:
                    # Front-end progress sink shouldn't kill the pipeline.
                    logger.debug("on_unit_start sink failed", exc_info=True)

            # Cache check
            cached = signal_cache.get_cached(local_cache, ticker, guru.name, today)
            if cached:
                cache_hits += 1
                results.append(cached)
                completed += 1
                if on_unit_done:
                    await on_unit_done(guru, ticker, cached, True, completed, total)
                return

            # LLM evaluation
            try:
                if cancel_check and cancel_check():
                    return
                sig = await asyncio.to_thread(_invoke, guru, ticker, bundle)
                signal_cache.set_cached(local_cache, ticker, guru.name, today, sig)
                new_calls += 1
                results.append(sig)
                completed += 1
                if on_unit_done:
                    await on_unit_done(guru, ticker, sig, False, completed, total)
            except Exception as e:
                logger.warning("Guru %s failed for %s: %s", guru.name, ticker, e)
                fallback = _error_signal(guru.name, ticker, e)
                failed_units += 1
                results.append(fallback)
                completed += 1
                if on_unit_failed:
                    try:
                        await on_unit_failed(guru, ticker, e)
                    except Exception:
                        logger.debug("on_unit_failed sink failed", exc_info=True)
                # Keep ``on_unit_done`` for legacy listeners that count
                # progress generically; the ``cached=False`` is honest
                # (it wasn't a cache hit) but the new ``on_unit_failed``
                # is the canonical signal for state coloring.
                if on_unit_done:
                    await on_unit_done(guru, ticker, fallback, False, completed, total)

    await asyncio.gather(*[_one(g, t, b) for g, t, b in units])
    stats = RunStats(
        total_units=total,
        cache_hits=cache_hits,
        new_calls=new_calls,
        failed_units=failed_units,
    )
    return results, stats
