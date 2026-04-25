"""Aggregator — combines 8 agent scores + guru matches into final conviction.

Conviction formula (per SCREENER_V2_TECH_DESIGN §2.2):
    conviction = 0.5  * agent_weighted_mean
               + 0.15 * agent_consensus          (1 - stdev/50, clipped 0..1)
               + 0.20 * guru_consistency         (frac of fit=true)
               + 0.15 * debate_score             (0 if skipped)

If debate is skipped, renormalize the first 3 terms to sum to 1.

Input per ticker:
    agent_scores:  {agent_name -> AgentScore}
    guru_matches:  {guru_name -> GuruMatch}
    debate_score:  float or None
    regime_weights: {agent_name -> weight}  (from RegimeResult)
"""

from __future__ import annotations

from statistics import pstdev
from stock_trading_system.utils import get_logger
from stock_trading_system.screener.v2.agents.base import AgentScore, score_to_grade
from stock_trading_system.screener.v2.gurus.base import GuruMatch

logger = get_logger("screener.v2.aggregator")


class Aggregator:
    """Compute final conviction and rank picks."""

    WEIGHT_AGENT = 0.50
    WEIGHT_CONSENSUS = 0.15
    WEIGHT_GURU = 0.20
    WEIGHT_DEBATE = 0.15

    def aggregate_one(
        self,
        agent_scores: dict[str, AgentScore],
        guru_matches: dict[str, GuruMatch],
        regime_weights: dict[str, float],
        debate_score: float | None = None,
    ) -> dict:
        """Aggregate a single ticker's scores into conviction + breakdown."""
        # Weighted mean of agent scores
        agent_weighted = self._weighted_mean(agent_scores, regime_weights)

        # Consensus: 1 - normalized stddev of agent scores
        scores = [s.score for s in agent_scores.values() if s is not None]
        if len(scores) >= 2:
            sd = pstdev(scores)
            consensus = max(0.0, min(1.0, 1.0 - sd / 50.0)) * 100
        else:
            consensus = 50.0

        # Guru consistency: fraction of enabled gurus with fit=true, scaled to 0..100
        # guru_matches values may be dict (already serialized) or GuruMatch objects.
        if guru_matches:
            def _is_fit(g):
                if isinstance(g, dict):
                    return bool(g.get("fit"))
                return bool(getattr(g, "fit", False))
            fit_count = sum(1 for g in guru_matches.values() if _is_fit(g))
            guru_consistency = (fit_count / len(guru_matches)) * 100
        else:
            guru_consistency = 50.0

        # Conviction: weighted sum
        if debate_score is None:
            # Renormalize first 3 weights to sum to 1
            w_sum = self.WEIGHT_AGENT + self.WEIGHT_CONSENSUS + self.WEIGHT_GURU
            conviction = (
                (self.WEIGHT_AGENT / w_sum) * agent_weighted
                + (self.WEIGHT_CONSENSUS / w_sum) * consensus
                + (self.WEIGHT_GURU / w_sum) * guru_consistency
            )
        else:
            conviction = (
                self.WEIGHT_AGENT * agent_weighted
                + self.WEIGHT_CONSENSUS * consensus
                + self.WEIGHT_GURU * guru_consistency
                + self.WEIGHT_DEBATE * float(debate_score)
            )

        conviction = round(max(0.0, min(100.0, conviction)), 1)

        # Count agents leaning bullish (score >= 60)
        bullish_agents = sum(1 for s in agent_scores.values() if s and s.score >= 60)
        total_agents = len(agent_scores)

        return {
            "conviction": conviction,
            "conviction_grade": score_to_grade(conviction),
            "breakdown": {
                "agent_weighted_mean": round(agent_weighted, 1),
                "agent_consensus": round(consensus, 1),
                "guru_consistency": round(guru_consistency, 1),
                "debate_score": round(debate_score, 1) if debate_score is not None else None,
            },
            "bullish_agents": bullish_agents,
            "total_agents": total_agents,
            "agent_scores": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in agent_scores.items()
            },
            "guru_matches": {
                k: (v.to_dict() if hasattr(v, "to_dict") else v)
                for k, v in guru_matches.items()
            },
        }

    def rank(
        self,
        ticker_results: dict[str, dict],
        top_n: int = 5,
    ) -> list[dict]:
        """Sort by conviction DESC, stable tie-break by ticker asc."""
        items = [
            {"ticker": t, **data}
            for t, data in ticker_results.items()
        ]
        items.sort(key=lambda x: (-x["conviction"], x["ticker"]))
        for i, item in enumerate(items[:top_n], start=1):
            item["rank"] = i
        return items[:top_n]

    @staticmethod
    def _weighted_mean(
        agent_scores: dict[str, AgentScore],
        weights: dict[str, float],
    ) -> float:
        """Compute weighted mean of agent scores. Missing weights default to equal."""
        if not agent_scores:
            return 0.0
        total_weight = 0.0
        total = 0.0
        for name, s in agent_scores.items():
            if s is None:
                continue
            w = float(weights.get(name, 0.0))
            if w <= 0:
                # Fall back to equal weighting for agents not in regime map
                w = 1.0 / len(agent_scores)
            total_weight += w
            total += s.score * w
        if total_weight == 0:
            return 0.0
        return total / total_weight
