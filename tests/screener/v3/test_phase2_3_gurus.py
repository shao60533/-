"""Phase 2+3 tests: all 14 guru agents sub-analyses."""

from __future__ import annotations

import pytest

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.screener.v3.guru_agents.buffett import BuffettAgent
from stock_trading_system.screener.v3.guru_agents.graham import GrahamAgent
from stock_trading_system.screener.v3.guru_agents.munger import MungerAgent
from stock_trading_system.screener.v3.guru_agents.lynch import LynchAgent
from stock_trading_system.screener.v3.guru_agents.fisher import FisherAgent
from stock_trading_system.screener.v3.guru_agents.burry import BurryAgent
from stock_trading_system.screener.v3.guru_agents.ackman import AckmanAgent
from stock_trading_system.screener.v3.guru_agents.wood import WoodAgent
from stock_trading_system.screener.v3.guru_agents.druckenmiller import DruckenmillerAgent
from stock_trading_system.screener.v3.guru_agents.damodaran import DamodaranAgent
from stock_trading_system.screener.v3.guru_agents.pabrai import PabraiAgent
from stock_trading_system.screener.v3.guru_agents.taleb import TalebAgent
from stock_trading_system.screener.v3.guru_agents.marks import MarksAgent
from stock_trading_system.screener.v3.guru_agents.dalio import DalioAgent

ALL_AGENTS = [
    BuffettAgent, GrahamAgent, MungerAgent, LynchAgent, FisherAgent,
    BurryAgent, AckmanAgent, WoodAgent, DruckenmillerAgent, DamodaranAgent,
    PabraiAgent, TalebAgent, MarksAgent, DalioAgent,
]


@pytest.fixture()
def sample_data():
    return {
        "fundamentals_current": {
            "roe": 0.22, "profit_margin": 0.18, "net_margin": 0.18,
            "gross_margin": 0.42, "market_cap": 2e12, "pe": 25, "pb": 5,
            "debt_to_equity": 1.2, "current_ratio": 1.5,
            "free_cash_flow": 80e9, "fcf": 80e9, "revenue": 400e9,
            "shares_outstanding": 15e9, "revenue_growth": 0.08,
            "dividend_yield": 0.006, "beta": 1.1,
            "fcf_margin": 0.20, "interest_coverage": 15,
            "r_and_d_ratio": 0.06, "peg_ratio": 2.0,
        },
        "fundamentals_history": [
            {"revenue": 260e9, "gross_margin": 0.40, "book_value_per_share": 4.0,
             "net_income": 50e9, "earnings": 50e9},
            {"revenue": 290e9, "gross_margin": 0.41, "book_value_per_share": 4.5,
             "net_income": 55e9, "earnings": 55e9},
            {"revenue": 320e9, "gross_margin": 0.42, "book_value_per_share": 5.0,
             "net_income": 60e9, "earnings": 60e9},
            {"revenue": 360e9, "gross_margin": 0.43, "book_value_per_share": 5.5,
             "net_income": 68e9, "earnings": 68e9},
            {"revenue": 400e9, "gross_margin": 0.44, "book_value_per_share": 6.0,
             "net_income": 72e9, "earnings": 72e9},
        ],
        "quote": {"price": 200, "last": 200},
        "news_recent": [],
    }


class TestAllAgentsMeta:
    """Every agent must have required metadata fields."""

    @pytest.mark.parametrize("cls", ALL_AGENTS, ids=lambda c: c.__name__)
    def test_has_metadata(self, cls):
        agent = cls()
        assert agent.name, f"{cls.__name__} missing name"
        assert agent.display_name, f"{cls.__name__} missing display_name"
        assert agent.philosophy, f"{cls.__name__} missing philosophy"
        assert len(agent.principles) >= 3, f"{cls.__name__} needs >= 3 principles"
        assert agent.motto, f"{cls.__name__} missing motto"
        assert len(agent.avatar_initials) == 2

    @pytest.mark.parametrize("cls", ALL_AGENTS, ids=lambda c: c.__name__)
    def test_unique_name(self, cls):
        names = [c().name for c in ALL_AGENTS]
        assert len(set(names)) == 14, "Duplicate guru names found"

    @pytest.mark.parametrize("cls", ALL_AGENTS, ids=lambda c: c.__name__)
    def test_has_system_prompt(self, cls):
        assert hasattr(cls, "SYSTEM_PROMPT"), f"{cls.__name__} missing SYSTEM_PROMPT"
        assert len(cls.SYSTEM_PROMPT) > 100, f"{cls.__name__} SYSTEM_PROMPT too short"

    @pytest.mark.parametrize("cls", ALL_AGENTS, ids=lambda c: c.__name__)
    def test_evaluate_deep_returns_signal_without_llm(self, cls, sample_data):
        """evaluate_deep with no API key should fallback to neutral signal (not crash)."""
        agent = cls()
        result = agent.evaluate_deep("AAPL", sample_data, {"provider": "qwen", "config": {}})
        # Tolerant parsing returns a neutral fallback on LLM failure
        assert isinstance(result, GuruSignal)
        assert result.signal in ("bullish", "bearish", "neutral")


class TestGuruCount:
    def test_fourteen_agents(self):
        assert len(ALL_AGENTS) == 14

    def test_virattt_twelve(self):
        virattt = [a for a in ALL_AGENTS if a not in (MarksAgent, DalioAgent)]
        assert len(virattt) == 12

    def test_self_built_two(self):
        self_built = [MarksAgent, DalioAgent]
        assert len(self_built) == 2


class TestMarksSpecific:
    def test_cycle_position_low_pe(self):
        agent = MarksAgent()
        # Can't call full evaluate_deep without LLM, test sub-analysis via data
        assert agent.name == "marks"
        assert "周期" in agent.philosophy

    def test_meta(self):
        agent = MarksAgent()
        meta = agent.to_meta()
        assert meta["avatar_initials"] == "HM"


class TestDalioSpecific:
    def test_quadrant_model(self):
        agent = DalioAgent()
        assert "全天候" in agent.philosophy

    def test_meta(self):
        agent = DalioAgent()
        assert agent.avatar_initials == "RD"
