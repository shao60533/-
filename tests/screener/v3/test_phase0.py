"""Phase 0 tests: dependencies, skeleton, base interfaces."""

from __future__ import annotations

import pytest


class TestDependencies:
    def test_pydantic_v2(self):
        import pydantic
        assert int(pydantic.__version__.split(".")[0]) >= 2

    def test_tenacity(self):
        import tenacity
        assert hasattr(tenacity, "retry")

    def test_langchain(self):
        import langchain
        assert hasattr(langchain, "__version__")

    def test_langchain_openai(self):
        from langchain_openai import ChatOpenAI
        assert ChatOpenAI is not None

    def test_langchain_google(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        assert ChatGoogleGenerativeAI is not None


class TestGuruSignalSchema:
    def test_valid_signal(self):
        from stock_trading_system.screener.v3.guru_agents.base import GuruSignal, SubAnalysis
        sig = GuruSignal(
            guru="buffett", ticker="AAPL", signal="bullish",
            confidence=0.85, reasoning="Strong moat",
            sub_analyses=[SubAnalysis(name="moat", score=8.5, details="Wide moat")],
            key_metrics={"intrinsic_value": 220.0},
            total_score=85.0,
        )
        assert sig.signal == "bullish"
        assert sig.confidence == 0.85
        assert len(sig.sub_analyses) == 1

    def test_invalid_signal_rejected(self):
        from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
        with pytest.raises(Exception):
            GuruSignal(
                guru="x", ticker="X", signal="maybe",  # invalid
                confidence=0.5, reasoning="", sub_analyses=[],
                total_score=50,
            )

    def test_confidence_bounds(self):
        from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
        with pytest.raises(Exception):
            GuruSignal(
                guru="x", ticker="X", signal="bullish",
                confidence=1.5,  # out of range
                reasoning="", sub_analyses=[], total_score=50,
            )

    def test_json_roundtrip(self):
        from stock_trading_system.screener.v3.guru_agents.base import GuruSignal, SubAnalysis
        sig = GuruSignal(
            guru="graham", ticker="MSFT", signal="neutral",
            confidence=0.6, reasoning="Fair value",
            sub_analyses=[SubAnalysis(name="net-net", score=3.0, details="N/A")],
            key_metrics={"margin_of_safety": 0.05},
            total_score=60.0,
        )
        json_str = sig.model_dump_json()
        restored = GuruSignal.model_validate_json(json_str)
        assert restored == sig


class TestBaseGuruAgent:
    def test_abstract_evaluate_raises(self):
        from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent
        agent = BaseGuruAgent()
        with pytest.raises(NotImplementedError):
            agent.evaluate_deep("AAPL", {}, {})

    def test_to_meta(self):
        from stock_trading_system.screener.v3.guru_agents.base import BaseGuruAgent
        agent = BaseGuruAgent()
        agent.name = "test"
        agent.display_name = "Test Guru"
        meta = agent.to_meta()
        assert meta["name"] == "test"
        assert meta["display_name"] == "Test Guru"


class TestEstimator:
    def test_basic_estimate(self):
        from stock_trading_system.screener.v3.estimator import estimate
        result = estimate(
            num_candidates=20, num_gurus=4,
            with_roundtable=False, provider="qwen",
        )
        assert result["llm_calls"] == 80
        assert result["cost_cny"] > 0
        assert result["duration_sec"] > 0

    def test_with_roundtable(self):
        from stock_trading_system.screener.v3.estimator import estimate
        r_no = estimate(20, 4, with_roundtable=False, provider="qwen")
        r_rt = estimate(20, 4, with_roundtable=True, provider="qwen")
        assert r_rt["llm_calls"] > r_no["llm_calls"]
        assert r_rt["duration_sec"] > r_no["duration_sec"]
        assert r_rt["cost_cny"] > r_no["cost_cny"]

    def test_gemini_cheaper(self):
        from stock_trading_system.screener.v3.estimator import estimate
        r_qwen = estimate(20, 4, False, "qwen")
        r_gemini = estimate(20, 4, False, "gemini")
        assert r_gemini["cost_cny"] < r_qwen["cost_cny"]
