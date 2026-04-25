"""Base class for screening agents (V2).

All 8 specialist agents inherit from BaseAgent. Each agent:
- Has a unique `name` (used in aggregator weights and UI)
- Declares its `data_source` (local_cache|qwen|yfinance|mixed) for UI tags
- Implements `score(ticker, context)` returning AgentScore
- Optionally overrides `score_batch(tickers, context)` for efficiency

Failures MUST NOT propagate — always return AgentScore(score=0, rationale="...error...")
so that one broken agent doesn't kill the whole screening run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any

from stock_trading_system.utils import get_logger

logger = get_logger("screener.v2.agent")


@dataclass
class AgentScore:
    """Score output for a single stock from a single agent."""
    score: float                     # 0-100
    grade: str                       # A+, A, B+, B, C+, C, D+, D, F
    rationale: str                   # 一句话说明
    signals: dict = field(default_factory=dict)  # 关键指标详情

    def to_dict(self) -> dict:
        return asdict(self)


_GRADE_BUCKETS = [
    (93, "A+"), (87, "A"), (80, "B+"), (73, "B"),
    (66, "C+"), (60, "C"), (50, "D+"), (40, "D"),
]


def score_to_grade(score: float) -> str:
    """Map 0-100 numeric score to Seeking-Alpha-style letter grade."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "F"
    for threshold, grade in _GRADE_BUCKETS:
        if s >= threshold:
            return grade
    return "F"


class BaseAgent(ABC):
    """Abstract base for a screening agent.

    Subclasses should set `name` and `data_source` as class attributes.
    """
    name: str = "base"
    data_source: str = "mixed"

    def __init__(self, config: dict):
        self._config = config

    @abstractmethod
    def score(self, ticker: str, context: dict) -> AgentScore:
        """Score a single ticker given a shared context dict.

        Context may include pre-fetched data (e.g. regime info, universe bars)
        to avoid duplicate lookups across agents.
        """
        raise NotImplementedError

    def score_batch(self, tickers: list[str], context: dict) -> dict[str, AgentScore]:
        """Default implementation: loop. Override for efficiency when possible."""
        out: dict[str, AgentScore] = {}
        for t in tickers:
            try:
                out[t] = self.score(t, context)
            except Exception as e:  # noqa: BLE001 — agent isolation
                logger.warning("%s.score(%s) failed: %s", self.name, t, e)
                out[t] = AgentScore(
                    score=0.0,
                    grade="F",
                    rationale=f"Agent error: {e}",
                    signals={"error": str(e)},
                )
        return out

    @staticmethod
    def make_score(
        score: float,
        rationale: str = "",
        signals: dict | None = None,
    ) -> AgentScore:
        """Convenience factory that computes grade from score."""
        s = max(0.0, min(100.0, float(score)))
        return AgentScore(
            score=round(s, 1),
            grade=score_to_grade(s),
            rationale=rationale,
            signals=signals or {},
        )
