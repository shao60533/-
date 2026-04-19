"""Cost and duration estimator for V3 guru evaluation runs."""

from __future__ import annotations

AVG_DURATION_PER_CALL_SEC = 5.0
AVG_TOKENS_IN = 2000
AVG_TOKENS_OUT = 500

PROVIDER_PRICING = {
    "qwen":   {"in": 0.008, "out": 0.020},
    "gemini": {"in": 0.002, "out": 0.006},
}


def estimate(
    num_candidates: int,
    num_gurus: int,
    with_roundtable: bool,
    provider: str,
    concurrency: int = 10,
) -> dict:
    """Estimate cost, duration, and token usage for a V3 screening run."""
    main_calls = num_candidates * num_gurus
    main_duration = (main_calls / concurrency) * AVG_DURATION_PER_CALL_SEC

    rt_calls = 15 if with_roundtable else 0
    rt_duration = 60 if with_roundtable else 0

    total_calls = main_calls + rt_calls
    tokens_in = total_calls * AVG_TOKENS_IN
    tokens_out = total_calls * AVG_TOKENS_OUT

    pricing = PROVIDER_PRICING.get(provider, PROVIDER_PRICING["qwen"])
    cost_cny = (tokens_in * pricing["in"] + tokens_out * pricing["out"]) / 1000

    return {
        "llm_calls": total_calls,
        "duration_sec": main_duration + rt_duration,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_cny": round(cost_cny, 2),
    }
