"""Darwinian weight management — promote top performers, demote laggards.

Constants adopted from atlas-elenchus (github.com/leonbreukelman/atlas-elenchus):
    WEIGHT_MIN  = 0.3   (floor)
    WEIGHT_MAX  = 2.5   (ceiling)
    WEIGHT_BOOST = 1.05 (top 25% daily multiplier)
    WEIGHT_DECAY = 0.95 (bottom 25% daily multiplier)
"""

from __future__ import annotations

from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
from stock_trading_system.agents.iterative.config import DarwinianConfig
from stock_trading_system.utils import get_logger

logger = get_logger("iterative.darwinian")

# Agent display names for the weight context prompt.
_DISPLAY_NAMES: dict[str, str] = {
    "market_analyst":       "Market Analyst",
    "sentiment_analyst":    "Sentiment Analyst",
    "news_analyst":         "News Analyst",
    "fundamentals_analyst": "Fundamentals Analyst",
    "bull_researcher":      "Bull Researcher",
    "bear_researcher":      "Bear Researcher",
    "trader":               "Trader",
}


def update_darwinian_weights(
    scorer: AgentScorer,
    config: DarwinianConfig | None = None,
) -> dict[str, float]:
    """Adjust weights: top 25% get boosted, bottom 25% get decayed.

    Args:
        scorer: AgentScorer with metrics and weights.
        config: Darwinian config (uses defaults if None).

    Returns:
        Updated weights dict {agent_id: new_weight}.
    """
    cfg = config or DarwinianConfig()
    if not cfg.enabled:
        return scorer.get_all_weights()

    metrics = scorer.get_all_agent_metrics()
    ranked = sorted(metrics.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    n = len(ranked)
    if n < 4:
        return scorer.get_all_weights()

    top_n = max(1, n // 4)
    bottom_n = max(1, n // 4)
    top_ids = {r[0] for r in ranked[:top_n]}
    bottom_ids = {r[0] for r in ranked[-bottom_n:]}

    updated: dict[str, float] = {}
    for agent_id, _m in ranked:
        old_w = scorer.get_weight(agent_id)
        if agent_id in top_ids:
            new_w = min(old_w * cfg.boost, cfg.ceiling)
        elif agent_id in bottom_ids:
            new_w = max(old_w * cfg.decay, cfg.floor)
        else:
            new_w = old_w
        scorer.save_weight(agent_id, new_w)
        updated[agent_id] = new_w

    logger.info("Darwinian weights updated — top: %s, bottom: %s",
                top_ids, bottom_ids)
    return updated


def format_weight_context(scorer: AgentScorer) -> str:
    """Generate the weight context string to inject into TradingAgents init_state.

    Format matches the spec:
        [Agent Reliability Weights — based on 30-day rolling Sharpe]
          Market Analyst:       1.85 ★ (top performer)
          ...
    """
    weights = scorer.get_all_weights()
    if not weights:
        return ""

    # Sort by weight descending
    sorted_agents = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    max_w = sorted_agents[0][1] if sorted_agents else 1.0
    min_w = sorted_agents[-1][1] if sorted_agents else 1.0

    lines = ["[Agent Reliability Weights — based on 30-day rolling Sharpe]"]
    for agent_id, w in sorted_agents:
        name = _DISPLAY_NAMES.get(agent_id, agent_id)
        suffix = ""
        if w == max_w and w > 1.0:
            suffix = " ★ (top performer)"
        elif w == min_w and w < 1.0:
            suffix = " ⚠ (underperforming)"
        lines.append(f"  {name + ':':<26} {w:.2f}{suffix}")

    lines.append("")
    lines.append(
        "When synthesizing agent reports, give proportionally more "
        "weight to higher-scored agents."
    )
    return "\n".join(lines)
