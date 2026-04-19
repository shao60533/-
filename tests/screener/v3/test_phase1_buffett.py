"""Phase 1 tests: BuffettAgent sub-analyses and integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal, SubAnalysis
from stock_trading_system.screener.v3.guru_agents.buffett import BuffettAgent


@pytest.fixture()
def agent():
    return BuffettAgent()


@pytest.fixture()
def sample_data():
    return {
        "fundamentals_current": {
            "roe": 0.25,
            "profit_margin": 0.22,
            "net_margin": 0.22,
            "market_cap": 3e12,
            "pe": 28,
            "debt_to_equity": 1.5,
            "free_cash_flow": 100e9,
            "shares_outstanding": 15e9,
            "revenue_growth": 0.08,
            "gross_margin": 0.45,
            "fcf_margin": 0.25,
        },
        "fundamentals_history": [
            {"revenue": 260e9, "gross_margin": 0.42, "book_value_per_share": 4.0},
            {"revenue": 275e9, "gross_margin": 0.43, "book_value_per_share": 4.5},
            {"revenue": 295e9, "gross_margin": 0.44, "book_value_per_share": 5.0},
            {"revenue": 320e9, "gross_margin": 0.45, "book_value_per_share": 5.5},
            {"revenue": 380e9, "gross_margin": 0.46, "book_value_per_share": 6.2},
        ],
        "quote": {"price": 200, "last": 200},
    }


class TestBuffettMeta:
    def test_name(self, agent):
        assert agent.name == "buffett"
        assert agent.display_name == "Warren Buffett"

    def test_to_meta(self, agent):
        meta = agent.to_meta()
        assert meta["avatar_initials"] == "WB"
        assert len(meta["principles"]) >= 3


class TestFundamentals:
    def test_high_roe(self, agent):
        result = agent._analyze_fundamentals({"roe": 0.30, "profit_margin": 0.25})
        assert result.score > 7

    def test_low_roe(self, agent):
        result = agent._analyze_fundamentals({"roe": 0.05, "profit_margin": 0.03})
        assert result.score < 5

    def test_missing_data(self, agent):
        result = agent._analyze_fundamentals({})
        assert result.name == "fundamental_quality"


class TestConsistency:
    def test_stable_growth(self, agent, sample_data):
        result = agent._analyze_consistency(sample_data["fundamentals_history"])
        assert result.score >= 6

    def test_insufficient_data(self, agent):
        result = agent._analyze_consistency([])
        assert "不足" in result.details

    def test_volatile_revenue(self, agent):
        history = [
            {"revenue": 100e9}, {"revenue": 50e9},
            {"revenue": 150e9}, {"revenue": 60e9},
        ]
        result = agent._analyze_consistency(history)
        assert result.score < 6


class TestMoat:
    def test_wide_moat(self, agent):
        result = agent._analyze_moat({"roe": 0.25, "profit_margin": 0.20, "market_cap": 200e9})
        assert result.score > 7

    def test_no_moat(self, agent):
        result = agent._analyze_moat({"roe": 0.05, "profit_margin": 0.03, "market_cap": 500e6})
        assert result.score <= 6


class TestPricingPower:
    def test_expanding_margins(self, agent, sample_data):
        result = agent._analyze_pricing_power(
            sample_data["fundamentals_current"],
            sample_data["fundamentals_history"],
        )
        assert result.score >= 6

    def test_no_data(self, agent):
        result = agent._analyze_pricing_power({}, [])
        assert "不足" in result.details


class TestBookValueGrowth:
    def test_growing(self, agent, sample_data):
        result = agent._analyze_book_value_growth(sample_data["fundamentals_history"])
        assert result.score >= 6

    def test_declining(self, agent):
        history = [
            {"book_value_per_share": 10},
            {"book_value_per_share": 8},
            {"book_value_per_share": 6},
        ]
        result = agent._analyze_book_value_growth(history)
        assert result.score < 5


class TestManagementQuality:
    def test_good_management(self, agent):
        result = agent._analyze_management_quality({"fcf_margin": 0.20, "debt_to_equity": 0.3})
        assert result.score > 7

    def test_poor_management(self, agent):
        result = agent._analyze_management_quality({"fcf_margin": -0.05, "debt_to_equity": 3.0})
        assert result.score < 4


class TestIntrinsicValue:
    def test_undervalued(self, agent, sample_data):
        result = agent._calculate_intrinsic_value(
            sample_data["fundamentals_current"],
            {"price": 50},  # very cheap
        )
        assert result["score"] >= 7

    def test_no_fcf(self, agent):
        result = agent._calculate_intrinsic_value({"free_cash_flow": 0}, {"price": 100})
        assert result["value"] == 0


class TestMarginOfSafety:
    def test_large_margin(self, agent):
        result = agent._calculate_margin_of_safety({"value": 200}, {"price": 100})
        assert result["margin"] > 0.4
        assert result["score"] >= 8

    def test_overvalued(self, agent):
        result = agent._calculate_margin_of_safety({"value": 100}, {"price": 150})
        assert result["margin"] < 0
        assert result["score"] < 5
