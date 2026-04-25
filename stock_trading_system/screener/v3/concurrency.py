"""Concurrent guru evaluation with semaphore + tenacity retry."""

from __future__ import annotations

import asyncio
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
) -> list[GuruSignal]:
    """Run guru evaluations concurrently with Semaphore(CONCURRENCY).

    Args:
        units: List of (guru_agent, ticker, data_bundle) tuples.
        context: Must contain 'provider' and 'config'.
        local_cache: LocalCache instance for (ticker, guru, date) caching.
        on_unit_done: Async callback(guru, ticker, signal, cached).
        cancel_check: Returns True to abort remaining units.

    Returns:
        List of GuruSignal results.
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[GuruSignal] = []
    completed = 0
    total = len(units)

    @_llm_retry
    def _invoke(guru: BaseGuruAgent, ticker: str, bundle: dict) -> GuruSignal:
        return guru.evaluate_deep(ticker, bundle, context)

    async def _one(guru: BaseGuruAgent, ticker: str, bundle: dict):
        nonlocal completed
        async with sem:
            if cancel_check and cancel_check():
                return

            # Cache check
            cached = signal_cache.get_cached(local_cache, ticker, guru.name, today)
            if cached:
                results.append(cached)
                completed += 1
                if on_unit_done:
                    await on_unit_done(guru, ticker, cached, True, completed, total)
                return

            # LLM evaluation
            try:
                sig = await asyncio.to_thread(_invoke, guru, ticker, bundle)
                signal_cache.set_cached(local_cache, ticker, guru.name, today, sig)
                results.append(sig)
                completed += 1
                if on_unit_done:
                    await on_unit_done(guru, ticker, sig, False, completed, total)
            except Exception as e:
                logger.warning("Guru %s failed for %s: %s", guru.name, ticker, e)
                fallback = _error_signal(guru.name, ticker, e)
                results.append(fallback)
                completed += 1
                if on_unit_done:
                    await on_unit_done(guru, ticker, fallback, False, completed, total)

    await asyncio.gather(*[_one(g, t, b) for g, t, b in units])
    return results
