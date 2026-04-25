"""Phase 4 tests: pipeline, concurrency, cache, estimator integration."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal, SubAnalysis
from stock_trading_system.screener.v3.cache import get_cached, set_cached, _cache_key
from stock_trading_system.screener.v3.concurrency import _error_signal
from stock_trading_system.screener.v3.pipeline import get_all_guru_metas, _load_guru_registry


class TestGuruRegistry:
    def test_load_all_14(self):
        registry = _load_guru_registry()
        assert len(registry) == 14

    def test_get_all_metas(self):
        metas = get_all_guru_metas()
        assert len(metas) == 14
        names = {m["name"] for m in metas}
        assert "buffett" in names
        assert "marks" in names
        assert "dalio" in names


class TestCache:
    def test_cache_key_format(self):
        key = _cache_key("AAPL", "buffett", "2026-04-19")
        assert key == "AAPL:buffett:2026-04-19"

    def test_get_cached_none_when_empty(self):
        result = get_cached(None, "AAPL", "buffett", "2026-04-19")
        assert result is None

    def test_set_and_get_with_mock_cache(self):
        mock_cache = MagicMock()
        sig = GuruSignal(
            guru="buffett", ticker="AAPL", signal="bullish",
            confidence=0.8, reasoning="test",
            sub_analyses=[], total_score=80,
        )
        # set should call mock_cache.set
        set_cached(mock_cache, "AAPL", "buffett", "2026-04-19", sig)
        mock_cache.set.assert_called_once()

        # get should call mock_cache.get
        mock_cache.get.return_value = sig.model_dump_json()
        result = get_cached(mock_cache, "AAPL", "buffett", "2026-04-19")
        assert result is not None
        assert result.guru == "buffett"


class TestErrorSignal:
    def test_creates_neutral_fallback(self):
        sig = _error_signal("buffett", "AAPL", RuntimeError("timeout"))
        assert sig.signal == "neutral"
        assert sig.confidence == 0.0
        assert "timeout" in sig.reasoning


class TestEstimatorIntegration:
    def test_consistency_with_pipeline_params(self):
        from stock_trading_system.screener.v3.estimator import estimate
        # 20 candidates × 4 gurus = 80 calls
        est = estimate(20, 4, False, "qwen")
        assert est["llm_calls"] == 80
        assert est["duration_sec"] == (80 / 10) * 5.0  # 40s


class TestPipelineClassicMode:
    def test_classic_returns_v2_engine(self):
        from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline
        pipe = ScreenerV3Pipeline(config={}, provider="qwen")
        result = asyncio.run(pipe._run_classic_mode(["AAPL", "MSFT"], {}))
        assert result["engine"] == "v2_classic"
        assert result["mode"] == "classic"


class TestPipelineAggregation:
    def test_aggregate_ranks_by_score(self):
        from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline
        pipe = ScreenerV3Pipeline(config={})
        signals = [
            GuruSignal(guru="buffett", ticker="AAPL", signal="bullish",
                       confidence=0.9, reasoning="", sub_analyses=[], total_score=90),
            GuruSignal(guru="graham", ticker="AAPL", signal="bullish",
                       confidence=0.7, reasoning="", sub_analyses=[], total_score=70),
            GuruSignal(guru="buffett", ticker="MSFT", signal="neutral",
                       confidence=0.5, reasoning="", sub_analyses=[], total_score=50),
        ]
        results = pipe._aggregate(["AAPL", "MSFT"], signals, {})
        assert results[0]["ticker"] == "AAPL"  # higher score first
        assert results[0]["final_score"] == 80.0  # avg of 90 + 70
        assert results[1]["ticker"] == "MSFT"
