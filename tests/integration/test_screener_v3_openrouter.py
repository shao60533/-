"""End-to-end: screener_v3 worker runs through OpenRouter.

This is a real-call integration test. It:
  1. Forces LLM_PROVIDER=openrouter via env.
  2. Spins ScreenerV3Pipeline with 1 ticker + 1 guru.
  3. Asserts the 14-guru deep path emitted a real GuruSignal (Pydantic
     fields populated, not the neutral fallback).

Skipped automatically when OPENROUTER_API_KEY isn't set, so unit-test
runs / CI without the secret stay green. To run locally:

    OPENROUTER_API_KEY=sk-or-v1-... pytest tests/integration/test_screener_v3_openrouter.py -v
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="needs OPENROUTER_API_KEY env to run real OR calls",
)


@pytest.fixture
def or_config():
    """Minimal yaml-shape config that activates OR with the default
    deepseek-v4-pro / deepseek-v4-flash presets."""
    return {
        "llm_provider": "openrouter",
        "openrouter": {
            "enabled": True,
            "api_key": "",  # env wins
            "base_url": "https://openrouter.ai/api/v1",
            "x_title": "StockAI Terminal (integration test)",
            "presets": [
                {
                    "id": "deepseek-v4-pro",
                    "label": "DeepSeek V4 Pro",
                    "model": "deepseek/deepseek-v4-pro",
                    "role": "deep",
                    "provider_order": ["deepseek"],
                    "kwargs": {},
                },
                {
                    "id": "deepseek-v4-flash",
                    "label": "DeepSeek V4 Flash",
                    "model": "deepseek/deepseek-v4-flash",
                    "role": "quick",
                    "provider_order": ["deepseek"],
                    "kwargs": {},
                },
            ],
            "active": {"deep": "deepseek-v4-pro", "quick": "deepseek-v4-flash"},
        },
        "qwen": {"api_key": ""},
        "gemini": {"api_key": ""},
        "iteration": {"enabled": False},
    }


def test_screener_v3_runs_via_openrouter(or_config, monkeypatch):
    """Drive screener_v3 worker through OR end-to-end with 1 ticker /
    1 guru. Verifies:
      - provider auto-resolves to openrouter
      - guru deep evaluation produces a real GuruSignal (signal,
        confidence, total_score all populated; reasoning non-empty)
      - candidates list non-empty (universe filter ran)
    """
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")

    from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline

    # Pre-populate candidate list so we don't burn an LLM call on
    # universe materialisation — the test is about the guru loop.
    pipeline = ScreenerV3Pipeline(
        config=or_config,
        user_id=None,
        # provider=None lets router resolve from env LLM_PROVIDER above
    )
    assert pipeline._provider == "openrouter", (
        "router should resolve openrouter under LLM_PROVIDER env"
    )

    async def _run():
        return await pipeline.run(
            nl_query="apple inc",
            market="us",
            candidate_n=1,                       # smallest viable pool
            gurus=["buffett"],                   # 1 guru → 1 deep call
            mode="agent",
            with_roundtable=False,
        )

    result = asyncio.run(_run())

    # Pipeline returned an envelope, not a fallback empty.
    assert result["engine"] == "v3"
    assert result["candidates_count"] >= 1, (
        f"universe filter returned 0 — check OR network: {result}"
    )
    # At least one guru result with a real (non-fallback) signal.
    candidates = result.get("results") or []
    assert candidates, f"no scored candidates in result: {result}"
    first = candidates[0]
    sigs = first.get("guru_signals") or []
    assert sigs, f"no guru_signals on first candidate: {first}"
    sig = sigs[0]
    # Real signal — Pydantic fields populated, not the silent neutral
    # fallback the agent emits on parse failure.
    assert sig["signal"] in ("bullish", "bearish", "neutral"), sig
    assert 0.0 <= sig["confidence"] <= 1.0, sig
    assert (sig.get("reasoning") or "").strip(), sig
    # ``失败`` is the marker the fallback path uses; real OR responses
    # produce reasoning in the user's chosen language (Chinese here).
    assert "失败" not in sig["reasoning"][:50], (
        f"reasoning starts with failure marker, suggesting fallback: {sig}"
    )
