"""hardening-iteration-v1 P3.1 step-2 — v3 sync wrapper contract.

The wrapper bridges v3's async, NL-query-driven pipeline to the v1
``screen(market, strategy) → list[dict]`` shape. Step-3 will flip
three legacy call sites (web/app.py:72, telegram_bot.py:288,
main.py:68) over to this wrapper.

This suite locks down the bridge:

  1. Strategy → NL query mapping is deterministic and covers every
     v1 strategy id (growth / value / momentum / low_volatility).
  2. ``_v3_result_to_v1_list()`` translates the v3 signal vocabulary
     (bullish / bearish / neutral / split) to v1 (BUY / SELL / HOLD).
  3. The wrapper survives a degenerate pipeline result (empty / wrong
     shape / None) without raising.
  4. Top bull/bear argument lands in v1's "summary" field with the
     200-char cap.
  5. nl_query_override bypasses the strategy mapping.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from stock_trading_system.screener.v3.sync_wrapper import (
    _STRATEGY_TO_NL_QUERY, _v3_result_to_v1_list, screen_sync,
)


# ── strategy → NL query map ────────────────────────────────────────────────


def test_every_v1_strategy_has_nl_query_mapping():
    """v1 STRATEGIES: growth / value / momentum / low_volatility."""
    for sid in ("growth", "value", "momentum", "low_volatility"):
        assert sid in _STRATEGY_TO_NL_QUERY, (
            f"missing NL query for v1 strategy id {sid!r}"
        )


def test_nl_query_includes_market_descriptor():
    """The query strings drive Qwen's NL parser; each must mention 美股
    so the market filter binds correctly."""
    for sid, q in _STRATEGY_TO_NL_QUERY.items():
        assert "美股" in q, f"{sid!r} NL query missing 美股: {q!r}"


# ── v3 → v1 result conversion ─────────────────────────────────────────────


def test_v3_to_v1_signal_translation():
    """v3 bullish/bearish/neutral/split → v1 BUY/SELL/HOLD/HOLD."""
    v3 = {
        "engine": "v3",
        "results": [
            {"ticker": "AAPL", "signal": "bullish"},
            {"ticker": "MSFT", "signal": "bearish"},
            {"ticker": "GOOG", "signal": "neutral"},
            {"ticker": "META", "signal": "split"},
            {"ticker": "TSLA", "signal": "weird-value"},
        ],
    }
    out = _v3_result_to_v1_list(v3)
    sigmap = {r["ticker"]: r["signal"] for r in out}
    assert sigmap == {
        "AAPL": "BUY", "MSFT": "SELL",
        "GOOG": "HOLD", "META": "HOLD",
        "TSLA": "HOLD",  # unknown signal collapses to HOLD
    }


def test_v3_to_v1_summary_capped_at_200():
    long_argument = "A" * 500
    v3 = {
        "results": [{
            "ticker": "AAPL", "signal": "bullish",
            "top_bull_argument": long_argument,
        }],
    }
    out = _v3_result_to_v1_list(v3)
    assert len(out[0]["summary"]) == 200


def test_v3_to_v1_falls_back_to_bear_argument_then_summary():
    """Summary precedence: top_bull > top_bear > summary > empty."""
    v3 = {
        "results": [
            {"ticker": "AAPL", "signal": "bearish",
             "top_bear_argument": "bearish thesis"},
            {"ticker": "MSFT", "signal": "neutral",
             "summary": "fallback summary"},
            {"ticker": "GOOG", "signal": "bullish"},  # nothing → ""
        ],
    }
    out = _v3_result_to_v1_list(v3)
    summaries = {r["ticker"]: r["summary"] for r in out}
    assert summaries == {
        "AAPL": "bearish thesis",
        "MSFT": "fallback summary",
        "GOOG": "",
    }


def test_v3_to_v1_handles_garbage_input():
    """Robust: every defensive branch returns [], not raise."""
    assert _v3_result_to_v1_list(None) == []
    assert _v3_result_to_v1_list({}) == []
    assert _v3_result_to_v1_list({"results": None}) == []
    assert _v3_result_to_v1_list({"results": "not a list"}) == []
    assert _v3_result_to_v1_list({"results": [None, "garbage", {}]}) == [
        {
            "ticker": "", "name": "", "sector": "",
            "signal": "HOLD", "summary": "", "score": 0,
            "v3_meta": {"votes": None, "consensus": None,
                         "confidence_range": None},
        },
    ]


def test_v3_to_v1_stashes_extras_in_v3_meta():
    """v1 consumers ignore v3_meta but the field carries votes /
    consensus / confidence_range so advanced UIs can opt in later."""
    v3 = {"results": [{
        "ticker": "AAPL", "signal": "bullish",
        "votes": {"bullish": 3, "bearish": 1},
        "consensus": "majority",
        "confidence_range": {"min": 0.4, "max": 0.9},
    }]}
    out = _v3_result_to_v1_list(v3)
    assert out[0]["v3_meta"]["votes"] == {"bullish": 3, "bearish": 1}
    assert out[0]["v3_meta"]["consensus"] == "majority"


# ── End-to-end via mocked pipeline ────────────────────────────────────────


def test_screen_sync_invokes_pipeline_with_mapped_nl_query():
    """screen_sync runs asyncio.run on ScreenerV3Pipeline.run, passing
    the strategy → NL query mapping. Mock the pipeline so we don't
    spin a real LLM call."""

    captured: dict = {}

    class _StubPipeline:
        def __init__(self, **kw):
            pass

        async def run(self, **kwargs):
            captured.update(kwargs)
            return {"results": [
                {"ticker": "AAPL", "signal": "bullish",
                 "top_bull_argument": "growth thesis"},
            ]}

    with patch(
        "stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline",
        new=_StubPipeline,
    ):
        result = screen_sync({}, market="us", strategy="growth")

    assert captured["nl_query"] == _STRATEGY_TO_NL_QUERY["growth"]
    assert captured["market"] == "us"
    assert captured["mode"] == "classic"
    assert captured["with_roundtable"] is False
    assert result == [{
        "ticker": "AAPL", "name": "", "sector": "",
        "signal": "BUY", "summary": "growth thesis", "score": 0,
        "v3_meta": {"votes": None, "consensus": None,
                     "confidence_range": None},
    }]


def test_screen_sync_nl_query_override_skips_mapping():
    captured: dict = {}

    class _StubPipeline:
        def __init__(self, **kw):
            pass

        async def run(self, **kwargs):
            captured.update(kwargs)
            return {"results": []}

    with patch(
        "stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline",
        new=_StubPipeline,
    ):
        screen_sync(
            {}, strategy="growth", nl_query_override="自定义查询",
        )

    assert captured["nl_query"] == "自定义查询"


def test_screen_sync_returns_empty_on_pipeline_error():
    """Pipeline blows up → wrapper logs + returns []. Legacy callers
    handle empty results gracefully."""
    class _BoomPipeline:
        def __init__(self, **kw):
            pass

        async def run(self, **kwargs):
            raise RuntimeError("LLM provider unavailable")

    with patch(
        "stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline",
        new=_BoomPipeline,
    ):
        result = screen_sync({}, market="us", strategy="value")
    assert result == []
