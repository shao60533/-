"""V2 screening agents."""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore, score_to_grade
from stock_trading_system.screener.v2.agents.momentum import MomentumAgent
from stock_trading_system.screener.v2.agents.quality_value import QualityValueAgent
from stock_trading_system.screener.v2.agents.catalyst import CatalystAgent
from stock_trading_system.screener.v2.agents.sentiment import SentimentAgent
from stock_trading_system.screener.v2.agents.technical import TechnicalAgent
from stock_trading_system.screener.v2.agents.regime_relative import RegimeRelativeAgent
from stock_trading_system.screener.v2.agents.guru import GuruAgent
from stock_trading_system.screener.v2.agents.risk import RiskAgent


def build_all(config: dict, data_helper) -> dict:
    """Factory: instantiate all 8 agents (except GuruAgent which is added last)."""
    return {
        "momentum": MomentumAgent(config, data_helper),
        "quality_value": QualityValueAgent(config, data_helper),
        "catalyst": CatalystAgent(config, data_helper),
        "sentiment": SentimentAgent(config, data_helper),
        "technical": TechnicalAgent(config, data_helper),
        "regime_relative": RegimeRelativeAgent(config, data_helper),
        "guru": GuruAgent(config, data_helper),
        "risk": RiskAgent(config, data_helper),
    }


__all__ = [
    "BaseAgent", "AgentScore", "score_to_grade",
    "MomentumAgent", "QualityValueAgent", "CatalystAgent",
    "SentimentAgent", "TechnicalAgent", "RegimeRelativeAgent",
    "GuruAgent", "RiskAgent",
    "build_all",
]
