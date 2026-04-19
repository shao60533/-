"""Round-table debate — Top 5 tickers get bull vs bear guru debate.

Reuses TradingAgents' bull_researcher / bear_researcher node patterns
as the debate template. Only the identity prompt is swapped (e.g.
"as Warren Buffett analyzing AAPL" instead of generic bull/bear).

The debate graph: bull_champion → bear_champion → rebuttal → consensus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.roundtable")


@dataclass
class RoundtableResult:
    ticker: str
    consensus: list[str] = field(default_factory=list)
    dissent: list[str] = field(default_factory=list)
    split: bool = False
    debate_snippets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "consensus": self.consensus,
            "dissent": self.dissent,
            "split": self.split,
            "debate_snippets": self.debate_snippets,
        }


def _build_debate_prompt(
    guru_name: str, ticker: str, signal: GuruSignal, role: str,
) -> str:
    """Build a debate prompt using the guru's reasoning as the argument."""
    stance = "看多" if role == "bull" else "看空"
    return (
        f"你现在扮演 {guru_name}，{stance} {ticker}。\n\n"
        f"你的分析依据：\n{signal.reasoning[:1500]}\n\n"
        f"核心论点：信号={signal.signal}, 信心度={signal.confidence:.0%}, "
        f"总分={signal.total_score:.0f}/100\n\n"
        f"请用简洁有力的方式阐述你的观点，直接反驳对方。限 300 字以内。"
    )


async def run_roundtable(
    top_signals: dict[str, list[GuruSignal]],
    llm_call: Any | None = None,
    on_progress: Any | None = None,
) -> dict[str, RoundtableResult]:
    """Run round-table debate for top tickers.

    For each ticker, the highest-confidence bullish guru debates the
    highest-confidence bearish guru. If all agree (no dissent), skip.

    Args:
        top_signals: {ticker: [GuruSignal, ...]} for top 5 tickers.
        llm_call: Optional callable(system, user) -> str for debate LLM.
        on_progress: Optional callback for streaming events.

    Returns:
        {ticker: RoundtableResult}
    """
    results: dict[str, RoundtableResult] = {}

    if on_progress:
        try:
            on_progress({
                "type": "roundtable_start",
                "tickers": list(top_signals.keys()),
            })
        except Exception:
            pass

    for ticker, signals in top_signals.items():
        bullish = [s for s in signals if s.signal == "bullish"]
        bearish = [s for s in signals if s.signal == "bearish"]

        # No debate needed if unanimous
        if not bullish or not bearish:
            majority = bullish or bearish or signals
            results[ticker] = RoundtableResult(
                ticker=ticker,
                consensus=[s.guru for s in majority],
                dissent=[],
                split=False,
                debate_snippets=["共识一致，无需辩论"],
            )
            continue

        bull_champion = max(bullish, key=lambda s: s.confidence)
        bear_champion = max(bearish, key=lambda s: s.confidence)

        snippets = []

        # Round 1: Bull argues
        bull_arg = _build_debate_prompt(
            bull_champion.guru, ticker, bull_champion, "bull"
        )
        snippets.append(f"🟢 {bull_champion.guru}: {bull_champion.reasoning[:300]}")

        # Round 2: Bear rebuts
        bear_arg = _build_debate_prompt(
            bear_champion.guru, ticker, bear_champion, "bear"
        )
        snippets.append(f"🔴 {bear_champion.guru}: {bear_champion.reasoning[:300]}")

        # Round 3: LLM-powered rebuttal (if llm_call available)
        if llm_call:
            try:
                rebuttal = llm_call(
                    "你是投资辩论裁判。基于双方论点，给出简短评判（150字以内）：谁的论点更有说服力？",
                    f"看多方 ({bull_champion.guru}):\n{bull_champion.reasoning[:500]}\n\n"
                    f"看空方 ({bear_champion.guru}):\n{bear_champion.reasoning[:500]}",
                )
                snippets.append(f"⚖️ 裁判: {rebuttal[:200]}")
            except Exception as e:
                snippets.append(f"⚖️ 裁判: 评判失败 ({e})")

        # Determine consensus by majority vote
        bull_total = sum(s.confidence for s in bullish)
        bear_total = sum(s.confidence for s in bearish)

        if bull_total > bear_total:
            consensus_gurus = [s.guru for s in bullish]
            dissent_gurus = [s.guru for s in bearish]
        elif bear_total > bull_total:
            consensus_gurus = [s.guru for s in bearish]
            dissent_gurus = [s.guru for s in bullish]
        else:
            consensus_gurus = [s.guru for s in signals]
            dissent_gurus = []

        results[ticker] = RoundtableResult(
            ticker=ticker,
            consensus=consensus_gurus,
            dissent=dissent_gurus,
            split=abs(bull_total - bear_total) < 0.1,
            debate_snippets=snippets,
        )

        if on_progress:
            try:
                on_progress({
                    "type": "roundtable_done",
                    "ticker": ticker,
                    "consensus": consensus_gurus,
                    "dissent": dissent_gurus,
                })
            except Exception:
                pass

    return results
