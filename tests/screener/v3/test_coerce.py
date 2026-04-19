"""Tests for _coerce_to_guru_signal — tolerant LLM output parsing."""

from __future__ import annotations

import pytest

from stock_trading_system.screener.v3.guru_agents.base import _coerce_to_guru_signal, GuruSignal


class TestSignalCoercion:
    def test_valid_signal_passes(self):
        sig = _coerce_to_guru_signal({"signal": "bullish"}, "test", "AAPL")
        assert sig.signal == "bullish"

    def test_avoid_maps_to_bearish(self):
        sig = _coerce_to_guru_signal({"signal": "avoid"}, "test", "AAPL")
        assert sig.signal == "bearish"

    def test_buy_maps_to_bullish(self):
        sig = _coerce_to_guru_signal({"signal": "buy"}, "test", "AAPL")
        assert sig.signal == "bullish"

    def test_hold_maps_to_neutral(self):
        sig = _coerce_to_guru_signal({"signal": "hold"}, "test", "AAPL")
        assert sig.signal == "neutral"

    def test_unknown_maps_to_neutral(self):
        sig = _coerce_to_guru_signal({"signal": "maybe"}, "test", "AAPL")
        assert sig.signal == "neutral"


class TestSubAnalysesCoercion:
    def test_dict_to_list(self):
        """Qwen returns sub_analyses as dict — should be converted to list."""
        raw = {
            "signal": "bullish",
            "sub_analyses": {
                "moat": 8.5,
                "valuation": {"score": 7.0, "details": "PE is reasonable"},
            },
        }
        sig = _coerce_to_guru_signal(raw, "buffett", "AAPL")
        assert isinstance(sig.sub_analyses, list)
        assert len(sig.sub_analyses) == 2
        names = {s.name for s in sig.sub_analyses}
        assert "moat" in names
        assert "valuation" in names

    def test_valid_list_preserved(self):
        raw = {
            "signal": "neutral",
            "sub_analyses": [
                {"name": "quality", "score": 6.0, "details": "ok"},
            ],
        }
        sig = _coerce_to_guru_signal(raw, "test", "AAPL")
        assert len(sig.sub_analyses) == 1
        assert sig.sub_analyses[0].name == "quality"

    def test_empty_list(self):
        sig = _coerce_to_guru_signal({"signal": "neutral", "sub_analyses": []}, "t", "X")
        assert sig.sub_analyses == []


class TestKeyMetricsCoercion:
    def test_string_values_filtered(self):
        """key_metrics with 'N/A' or text strings should be dropped."""
        raw = {
            "signal": "neutral",
            "key_metrics": {
                "intrinsic_value": 220.0,
                "margin_of_safety": "N/A",
                "assessment": "Fairly Valued",
                "pe_ratio": 25.5,
            },
        }
        sig = _coerce_to_guru_signal(raw, "test", "AAPL")
        assert "intrinsic_value" in sig.key_metrics
        assert sig.key_metrics["intrinsic_value"] == 220.0
        assert "pe_ratio" in sig.key_metrics
        assert "margin_of_safety" not in sig.key_metrics
        assert "assessment" not in sig.key_metrics

    def test_all_numeric_preserved(self):
        raw = {"signal": "bullish", "key_metrics": {"a": 1.0, "b": 2.5}}
        sig = _coerce_to_guru_signal(raw, "t", "X")
        assert len(sig.key_metrics) == 2


class TestConfidenceCoercion:
    def test_clamped_above_1(self):
        sig = _coerce_to_guru_signal({"signal": "bullish", "confidence": 95}, "t", "X")
        assert sig.confidence == 1.0

    def test_clamped_below_0(self):
        sig = _coerce_to_guru_signal({"signal": "bearish", "confidence": -0.5}, "t", "X")
        assert sig.confidence == 0.0

    def test_string_parsed(self):
        sig = _coerce_to_guru_signal({"signal": "neutral", "confidence": "0.75"}, "t", "X")
        assert sig.confidence == 0.75

    def test_invalid_defaults(self):
        sig = _coerce_to_guru_signal({"signal": "neutral", "confidence": "high"}, "t", "X")
        assert sig.confidence == 0.5


class TestMissingFields:
    def test_minimal_input(self):
        sig = _coerce_to_guru_signal({}, "graham", "MSFT")
        assert sig.guru == "graham"
        assert sig.ticker == "MSFT"
        assert sig.signal == "neutral"
        assert sig.confidence == 0.5
        assert sig.reasoning == ""

    def test_total_score_clamped(self):
        sig = _coerce_to_guru_signal({"total_score": 150}, "t", "X")
        assert sig.total_score == 100.0

    def test_total_score_negative(self):
        sig = _coerce_to_guru_signal({"total_score": -10}, "t", "X")
        assert sig.total_score == 0.0


class TestGeminiCompatibility:
    """Gemini may return slightly different structures."""

    def test_gemini_style_response(self):
        """Gemini often returns well-structured JSON but may use different field names."""
        raw = {
            "guru": "buffett",
            "ticker": "AAPL",
            "signal": "bullish",
            "confidence": 0.82,
            "reasoning": "Strong fundamentals and moat",
            "sub_analyses": [
                {"name": "moat", "score": 9.0, "details": "Ecosystem lock-in"},
            ],
            "key_metrics": {"intrinsic_value": 210.5, "pe_ratio": 28.0},
            "total_score": 85.0,
        }
        sig = _coerce_to_guru_signal(raw, "buffett", "AAPL")
        assert sig.signal == "bullish"
        assert sig.confidence == 0.82
        assert sig.total_score == 85.0
