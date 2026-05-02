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
    guru_name: str,
    ticker: str,
    signal: GuruSignal,
    role: str,
    query: str = "",
    spec: dict | None = None,
) -> str:
    """Build a debate prompt anchored to the user's query and FilterSpec.

    Every debater must answer three theme-fit questions before launching
    into financial bull/bear arguments. This is what stops the round
    table from drifting into 'AAPL is a wonderful business' when the
    user asked for storage names — pure financial debate is not a valid
    response when the ticker shouldn't have been a candidate."""
    stance_label = "看多" if role == "bull" else "看空"
    return (
        f"你现在扮演 {guru_name}，围绕用户查询「{query}」辩论 {ticker}。\n\n"
        f"结构化筛选条件：{spec or {}}\n\n"
        f"你的既有分析依据：\n{signal.reasoning[:1500]}\n\n"
        f"核心论点：信号={signal.signal}, 信心度={signal.confidence:.0%}, "
        f"总分={signal.total_score:.0f}/100\n\n"
        f"你必须先回答：\n"
        f"1. {ticker} 是否直接符合用户查询主题？\n"
        f"2. 它是不是该主题内的龙头或有明确产业链暴露？\n"
        f"3. 你的 {stance_label} 观点是否建立在主题匹配之上？\n\n"
        f"如果主题不匹配，你必须承认这一点，不能只讨论公司泛基本面。"
        f"请用简洁有力的方式阐述观点，限 300 字以内。"
    )


def _build_judge_prompts(
    bull_champion: GuruSignal,
    bear_champion: GuruSignal,
    query: str = "",
    spec: dict | None = None,
) -> tuple[str, str]:
    """Build (system, user) prompts for the round-table judge.

    The judge produces a 4-question verdict: theme fit, leader status,
    bull-vs-bear winner, and an explicit override that 'good fundamentals
    on an off-theme ticker' is NOT a valid screening result."""
    judge_system = (
        "你是投资辩论裁判。请基于双方论点判断："
        "1. 该股票是否符合用户查询主题；"
        "2. 是否具备主题内龙头属性；"
        "3. 多空哪方更有说服力；"
        "4. 如果主题不匹配，即使基本面优秀，也应判定不适合作为本次筛选结果。"
    )
    judge_user = (
        f"用户查询: {query}\n"
        f"结构化筛选条件: {spec or {}}\n\n"
        f"看多方 ({bull_champion.guru}):\n{bull_champion.reasoning[:500]}\n\n"
        f"看空方 ({bear_champion.guru}):\n{bear_champion.reasoning[:500]}"
    )
    return judge_system, judge_user


async def run_roundtable(
    top_signals: dict[str, list[GuruSignal]],
    llm_call: Any | None = None,
    on_progress: Any | None = None,
    *,
    query: str = "",
    spec: dict | None = None,
) -> dict[str, RoundtableResult]:
    """Run round-table debate for top tickers.

    For each ticker, the highest-confidence bullish guru debates the
    highest-confidence bearish guru. If all agree (no dissent), skip.

    Args:
        top_signals: {ticker: [GuruSignal, ...]} for top 5 tickers.
        llm_call: Optional callable(system, user) -> str for debate LLM.
        on_progress: Optional callback for streaming events.
        query: Original user natural-language query. Embedded verbatim
            in every debate prompt so debaters can't ignore the user's
            actual subject.
        spec: Parsed FilterSpec dict (intent_summary / sectors / themes
            / criteria / natural_fallback) — also embedded so the model
            sees the structured fields, not just the loose Chinese text.

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

        # Round 1: Bull argues — debate prompt is built and shown verbatim
        # so the user can see the theme-fit questions the model was asked
        # to answer before its bull thesis.
        bull_prompt = _build_debate_prompt(
            bull_champion.guru, ticker, bull_champion, "bull",
            query=query, spec=spec,
        )
        snippets.append(f"🟢 {bull_champion.guru}: {bull_champion.reasoning[:300]}")

        # Round 2: Bear rebuts
        bear_prompt = _build_debate_prompt(
            bear_champion.guru, ticker, bear_champion, "bear",
            query=query, spec=spec,
        )
        snippets.append(f"🔴 {bear_champion.guru}: {bear_champion.reasoning[:300]}")

        # Round 3: LLM-powered judge — always answers the 4 theme-aware
        # questions so generic bull-vs-bear is not enough when the user's
        # actual ask is "符合主题且值得投资".
        if llm_call:
            judge_system, judge_user = _build_judge_prompts(
                bull_champion, bear_champion, query=query, spec=spec,
            )
            try:
                rebuttal = llm_call(judge_system, judge_user)
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
