"""v1.2: ``ScreenerV3Pipeline._aggregate`` writes the canonical verdict
into ``candidate.signal`` so the result-page table never falls back to
``_derive_candidate_signal``. Also pins the consensus / votes /
confidence_range / top_*_argument fields the frontend renders."""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline


def _sig(ticker, guru, signal, conf, score=50, reasoning="r"):
    return GuruSignal(
        ticker=ticker, guru=guru, signal=signal,
        confidence=conf, total_score=score, reasoning=reasoning,
        sub_analyses=[],
    )


def test_aggregate_writes_verdict_unanimous_bullish():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("AMD", "lynch",   "bullish", 0.90),
        _sig("AMD", "buffett", "bullish", 0.85),
        _sig("AMD", "munger",  "bullish", 0.80),
        _sig("AMD", "graham",  "bullish", 0.75),
    ]
    [r] = p._aggregate(["AMD"], sigs, {})
    assert r["signal"] == "bullish"
    assert r["consensus"] == "unanimous"
    assert r["votes"] == {
        "bullish": 4, "bearish": 0, "neutral": 0, "total": 4,
    }
    # Highest-confidence bull surfaces in top_bull_argument.
    assert r["top_bull_argument"]["guru"] == "lynch"
    assert r["top_bull_argument"]["confidence"] == 0.90
    # No bears → no top_bear_argument.
    assert r["top_bear_argument"] is None


def test_aggregate_split_when_tied():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("MU", "a", "bullish", 0.80),
        _sig("MU", "b", "bullish", 0.70),
        _sig("MU", "c", "bearish", 0.90),
        _sig("MU", "d", "bearish", 0.60),
    ]
    [r] = p._aggregate(["MU"], sigs, {})
    assert r["signal"] == "split"
    assert r["consensus"] == "split"
    assert r["votes"]["bullish"] == 2
    assert r["votes"]["bearish"] == 2
    # Both sides surface their highest-confidence argument.
    assert r["top_bull_argument"]["confidence"] == 0.80
    assert r["top_bear_argument"]["confidence"] == 0.90


def test_aggregate_majority_bullish():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("X", "a", "bullish", 0.80),
        _sig("X", "b", "bullish", 0.70),
        _sig("X", "c", "bullish", 0.60),
        _sig("X", "d", "bearish", 0.90),
        _sig("X", "e", "neutral", 0.50),
    ]
    [r] = p._aggregate(["X"], sigs, {})
    assert r["signal"] == "bullish"
    assert r["consensus"] in ("majority", "unanimous")
    assert r["votes"]["bullish"] == 3
    assert r["votes"]["bearish"] == 1
    assert r["votes"]["neutral"] == 1
    assert r["votes"]["total"] == 5


def test_aggregate_unanimous_neutral_when_no_directional_signals():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("X", "a", "neutral", 0.50),
        _sig("X", "b", "neutral", 0.40),
    ]
    [r] = p._aggregate(["X"], sigs, {})
    assert r["signal"] == "neutral"
    assert r["consensus"] == "unanimous"


def test_aggregate_confidence_range_min_max_avg():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("X", "a", "bullish", 0.30),
        _sig("X", "b", "bullish", 0.60),
        _sig("X", "c", "bullish", 0.90),
    ]
    [r] = p._aggregate(["X"], sigs, {})
    cr = r["confidence_range"]
    assert cr["min"] == 0.30
    assert cr["max"] == 0.90
    assert cr["avg"] == 0.60


def test_aggregate_top_arguments_truncate_reasoning():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    long_reason = "x" * 500
    sigs = [_sig("X", "a", "bullish", 0.9, reasoning=long_reason)]
    [r] = p._aggregate(["X"], sigs, {})
    assert len(r["top_bull_argument"]["snippet"]) == 200


def test_aggregate_preserves_v10_fields():
    """Backwards compat — v1.0 callers still see final_score /
    avg_confidence / guru_signals / roundtable in the same place."""
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [_sig("X", "a", "bullish", 0.8, score=70)]
    [r] = p._aggregate(["X"], sigs, {})
    assert r["final_score"] == 70.0
    assert r["avg_confidence"] == 0.80
    assert isinstance(r["guru_signals"], list)
    assert "roundtable" in r


def test_aggregate_serializes_roundtable_dataclass():
    """``RoundtableResult`` is a dataclass — _aggregate must convert it
    to a dict so the worker's ``json.dumps`` doesn't crash later."""
    from stock_trading_system.screener.v3.roundtable import RoundtableResult

    rt = RoundtableResult(
        ticker="X",
        consensus=["lynch", "buffett"],
        dissent=["dalio"],
        split=True,
        debate_snippets=["🟢 lynch: bull", "🔴 dalio: bear", "⚖️ judge: hold"],
    )
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [_sig("X", "lynch", "bullish", 0.9)]
    [r] = p._aggregate(["X"], sigs, {"X": rt})
    assert isinstance(r["roundtable"], dict)
    assert r["roundtable"]["ticker"] == "X"
    assert r["roundtable"]["split"] is True
    assert r["roundtable"]["debate_snippets"][0].startswith("🟢")

    # Sanity: the whole result is JSON-serializable.
    import json
    blob = json.dumps([r], ensure_ascii=False)
    assert "RoundtableResult" not in blob


def test_aggregate_skips_tickers_with_no_signals():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    out = p._aggregate(["A", "B"], [_sig("A", "x", "bullish", 0.5)], {})
    assert [r["ticker"] for r in out] == ["A"]


def test_aggregate_sorts_by_final_score_desc():
    p = ScreenerV3Pipeline.__new__(ScreenerV3Pipeline)
    sigs = [
        _sig("LOW", "a", "bullish", 0.5, score=20),
        _sig("HIGH", "a", "bullish", 0.5, score=80),
        _sig("MID", "a", "bullish", 0.5, score=50),
    ]
    out = p._aggregate(["LOW", "HIGH", "MID"], sigs, {})
    assert [r["ticker"] for r in out] == ["HIGH", "MID", "LOW"]
