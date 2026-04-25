"""Phase 5 tests: round-table debate."""

from __future__ import annotations

import asyncio

import pytest

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal, SubAnalysis
from stock_trading_system.screener.v3.roundtable import (
    RoundtableResult,
    run_roundtable,
    _build_debate_prompt,
)


def _make_signal(guru, ticker, signal, confidence, score=70):
    return GuruSignal(
        guru=guru, ticker=ticker, signal=signal,
        confidence=confidence, reasoning=f"{guru} analysis for {ticker}",
        sub_analyses=[], total_score=score,
    )


class TestRoundtableResult:
    def test_to_dict(self):
        r = RoundtableResult(
            ticker="AAPL",
            consensus=["buffett", "graham"],
            dissent=["burry"],
            debate_snippets=["test"],
        )
        d = r.to_dict()
        assert d["ticker"] == "AAPL"
        assert len(d["consensus"]) == 2


class TestBuildDebatePrompt:
    def test_bull_prompt(self):
        sig = _make_signal("buffett", "AAPL", "bullish", 0.9)
        prompt = _build_debate_prompt("Warren Buffett", "AAPL", sig, "bull")
        assert "看多" in prompt
        assert "AAPL" in prompt

    def test_bear_prompt(self):
        sig = _make_signal("burry", "AAPL", "bearish", 0.8)
        prompt = _build_debate_prompt("Michael Burry", "AAPL", sig, "bear")
        assert "看空" in prompt


class TestRunRoundtable:
    def test_unanimous_bull_skips_debate(self):
        signals = {
            "AAPL": [
                _make_signal("buffett", "AAPL", "bullish", 0.9),
                _make_signal("graham", "AAPL", "bullish", 0.7),
            ],
        }
        results = asyncio.run(run_roundtable(signals))
        assert "AAPL" in results
        assert results["AAPL"].split is False
        assert "共识" in results["AAPL"].debate_snippets[0]

    def test_mixed_signals_triggers_debate(self):
        signals = {
            "TSLA": [
                _make_signal("wood", "TSLA", "bullish", 0.85),
                _make_signal("buffett", "TSLA", "bullish", 0.6),
                _make_signal("burry", "TSLA", "bearish", 0.9),
                _make_signal("taleb", "TSLA", "bearish", 0.7),
            ],
        }
        results = asyncio.run(run_roundtable(signals))
        r = results["TSLA"]
        assert len(r.debate_snippets) >= 2  # at least bull + bear arguments
        assert len(r.consensus) > 0

    def test_consensus_follows_confidence_weighted_majority(self):
        signals = {
            "MSFT": [
                _make_signal("buffett", "MSFT", "bullish", 0.9),
                _make_signal("graham", "MSFT", "bullish", 0.8),
                _make_signal("burry", "MSFT", "bearish", 0.5),
            ],
        }
        results = asyncio.run(run_roundtable(signals))
        r = results["MSFT"]
        assert "buffett" in r.consensus  # bull side wins
        assert "burry" in r.dissent

    def test_with_llm_judge(self):
        signals = {
            "NVDA": [
                _make_signal("wood", "NVDA", "bullish", 0.8),
                _make_signal("taleb", "NVDA", "bearish", 0.7),
            ],
        }
        mock_llm = lambda s, u: "看多方论据更充分"
        results = asyncio.run(run_roundtable(signals, llm_call=mock_llm))
        r = results["NVDA"]
        assert any("裁判" in s for s in r.debate_snippets)

    def test_progress_callback(self):
        events = []
        signals = {
            "GOOG": [
                _make_signal("damodaran", "GOOG", "bullish", 0.7),
                _make_signal("marks", "GOOG", "bearish", 0.6),
            ],
        }
        results = asyncio.run(run_roundtable(signals, on_progress=events.append))
        types = [e["type"] for e in events]
        assert "roundtable_start" in types
        assert "roundtable_done" in types

    def test_empty_signals(self):
        results = asyncio.run(run_roundtable({}))
        assert results == {}

    def test_multiple_tickers(self):
        signals = {
            "AAPL": [_make_signal("buffett", "AAPL", "bullish", 0.9)],
            "TSLA": [
                _make_signal("wood", "TSLA", "bullish", 0.8),
                _make_signal("burry", "TSLA", "bearish", 0.7),
            ],
        }
        results = asyncio.run(run_roundtable(signals))
        assert len(results) == 2
