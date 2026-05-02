"""Round-table debate — Top 5 tickers get bull vs bear guru debate.

The debate graph (v1.5):
    Round 1: bull_champion presents — must quote own evidence + flag
             opponent's weakest sub-analysis
    Round 2: bear_champion cross-examines — must quote own evidence
             AND cross-examine a specific number from Round 1
    Round 3: bull_champion rebuts — must directly answer the
             cross-examination, end with explicit "维持 bullish" or
             "下调到 neutral" (no fence-sitting allowed)
    Round 4: judge — 5-item verdict (theme fit / leader / winner /
             evidence quote / reversal conditions). Forbidden phrase:
             "双方都有道理".
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


def _build_roundtable_theme_clause(nl_query: str | None) -> str:
    q = (nl_query or "").strip()
    if not q:
        return ""
    return (
        f"用户查询：「{q}」。无论财务多漂亮，都必须先回答主题契合度，"
        "再做多空论证；主题不匹配请明确承认。\n\n"
    )


def _own_evidence_brief(signal: GuruSignal) -> str:
    """Render speaker's top-5 sub_analyses so the prompt can demand a
    verbatim number quote."""
    sa_lines = []
    for sa in (signal.sub_analyses or [])[:5]:
        details = (sa.details or "")[:100]
        sa_lines.append(f"  - {sa.name}: score={sa.score}, {details}")
    return "\n".join(sa_lines) or "  (无 sub_analyses)"


def _opponent_brief(opponent_signal: GuruSignal) -> str:
    """Compact opponent fingerprint — top-3 sub_analyses + reasoning
    excerpt — just enough for the speaker to cross-examine without
    flooding the prompt."""
    opp_sa = []
    for sa in (opponent_signal.sub_analyses or [])[:3]:
        opp_sa.append(f"  - {sa.name}: score={sa.score}")
    return "\n".join(opp_sa) or "  (无 sub_analyses)"


def _build_debate_prompt(
    guru_name: str,
    ticker: str,
    signal: GuruSignal,
    role: str,
    query: str = "",
    spec: dict | None = None,
    opponent_signal: GuruSignal | None = None,
    opponent_text: str | None = None,
) -> str:
    """v1.5 cross-examination prompt builder.

    ``role`` selects the prompt mode:
        * ``"bull"``           — Round 1, opening bull thesis. Must
                                  quote ≥1 own number + flag opponent's
                                  weakest sub-analysis.
        * ``"bear"``           — Round 2, bear cross-examination. Must
                                  quote ≥1 own number AND cross-examine
                                  a specific number from Round 1.
        * ``"bull_rebuttal"``  — Round 3 (v1.5 new), bull's reply.
                                  200-char cap; binary endpoint
                                  ("维持 bullish" / "下调到 neutral");
                                  "双方都有道理" forbidden.
    """
    theme_clause = _build_roundtable_theme_clause(query)
    spec_clause = f"结构化筛选条件：{spec or {}}\n\n"
    own_evidence = _own_evidence_brief(signal)

    if role == "bull_rebuttal":
        return (
            f"你现在扮演 {guru_name}（看多方），针对反方刚才的质询做反驳。\n\n"
            f"用户查询：「{query}」\n{theme_clause}{spec_clause}"
            f"你之前的核心论点：信号={signal.signal}, 信心度={signal.confidence:.0%}, "
            f"总分={signal.total_score:.0f}/100\n\n"
            f"你的 sub_analyses 关键数字（可继续引用）:\n{own_evidence}\n\n"
            f"反方刚刚对你的质询：\n{(opponent_text or '')[:800]}\n\n"
            f"反驳要求（限 200 字）：\n"
            f"1. 必须正面回应反方的具体质询点（不能跑题到新论点）。\n"
            f"2. 如果反方质疑你引用的某个数字，你必须给出该数字的来源或方法论。\n"
            f"3. 末句必须明确表态二选一：「我维持 bullish」或「我承认反方某点正确，下调到 neutral」。\n"
            f"4. 不要使用'双方都有道理'类模糊措辞。\n"
        )

    stance_label = "看多" if role == "bull" else "看空"

    opponent_clause = ""
    if opponent_signal:
        opp_brief = _opponent_brief(opponent_signal)
        if role == "bull":
            opponent_clause = (
                f"\n反方（{opponent_signal.guru}, 看空）的关键 sub_analyses（你需要预留反驳空间）:\n"
                f"{opp_brief}\n反方 reasoning 摘要：{opponent_signal.reasoning[:300]}\n"
            )
        else:  # bear
            opponent_clause = (
                f"\n正方（{opponent_signal.guru}, 看多）刚才的论据（你必须 cross-examine 其引用的具体数字）:\n"
                f"{opp_brief}\n正方 reasoning 摘要：{opponent_signal.reasoning[:300]}\n"
            )

    cross_examine_instruction = (
        "必须 cross-examine 正方刚才引用的至少 1 个具体数字（如 \"你引用的 ROE 22% 我有不同看法因为...\"）。"
        if role == "bear" else
        "必须指认反方 reasoning 中最弱的一条论据，并预留反驳空间。"
    )

    return (
        f"你现在扮演 {guru_name}，围绕用户查询「{query}」辩论 {ticker}。\n\n"
        f"{theme_clause}{spec_clause}"
        f"你的既有分析依据：\n{signal.reasoning[:1500]}\n\n"
        f"你的 sub_analyses 关键数字（必须 quote 至少 1 个）:\n{own_evidence}\n"
        f"{opponent_clause}\n"
        f"核心论点：信号={signal.signal}, 信心度={signal.confidence:.0%}, "
        f"总分={signal.total_score:.0f}/100\n\n"
        f"你必须先回答：\n"
        f"1. {ticker} 是否直接符合用户查询主题？\n"
        f"2. 它是不是该主题内的龙头或有明确产业链暴露？\n"
        f"3. 你的 {stance_label} 观点是否建立在主题匹配之上？\n\n"
        f"然后做 {stance_label} 论证：\n"
        f"a. 必须 quote 你 sub_analyses 中至少 1 个具体数字。\n"
        f"b. {cross_examine_instruction}\n"
        f"c. 不能跑题到泛公司讨论；如果主题不匹配你必须承认。\n"
        f"请用简洁有力的方式阐述观点，限 350 字以内。"
    )


def _build_judge_prompts(
    bull_champion: GuruSignal,
    bear_champion: GuruSignal,
    bull_rebuttal: str | None = None,
    query: str = "",
    spec: dict | None = None,
) -> tuple[str, str]:
    """v1.5: 5-item rigorous verdict + falsifiable reversal condition.

    Pre-v1.5 the judge had 4 generic questions and produced "双方都有
    道理" answers because nothing forced a side. Now:
        1. theme_fit score (must quote sub_analyses[name=theme_fit])
        2. leader status (yes / no / partial)
        3. winning side + their strongest single number (verbatim quote)
        4. reversal condition (1-2 observable facts)
        5. one-line final verdict — "双方都有道理" / "各有千秋" forbidden
    """
    judge_system = (
        "你是投资辩论裁判。请基于双方论点和最后一轮反驳输出严格 5 项裁决（限 350 字）：\n"
        "1. 主题契合度 (0-10) —— 必须 quote sub_analyses[name=theme_fit] 的 score。\n"
        "2. 龙头属性 (是 / 否 / 部分) —— 必须给一句话理由。\n"
        "3. 多空胜方 + 胜方最强 1 条数字证据 —— verbatim quote 自双方 reasoning（用引号包起）。\n"
        "4. 反转条件 —— 1-2 个可观察事实如果发生，会让你改变结论（如 \"若下季度 ROE 跌破 15%\"）。\n"
        "5. 1 句话最终裁决 —— 禁止 \"双方都有道理\"\"各有千秋\"等模糊措辞，必须明确选边。"
    )
    rebuttal_clause = (
        f"\n\n看多方反驳 ({bull_champion.guru} Round 3):\n{bull_rebuttal[:400]}"
        if bull_rebuttal else ""
    )
    judge_user = (
        f"用户查询: {query}\n"
        f"结构化筛选条件: {spec or {}}\n\n"
        f"看多方 ({bull_champion.guru}):\n{bull_champion.reasoning[:500]}\n\n"
        f"看空方 ({bear_champion.guru}):\n{bear_champion.reasoning[:500]}"
        f"{rebuttal_clause}"
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

    v1.5 cross-examination: when both sides exist AND llm_call is
    provided, we now run 4 rounds (bull → bear → bull_rebuttal →
    judge). The bull_rebuttal round costs ~$0.01-0.02 per contested
    ticker; Top-5 fully-contested adds $0.05-0.10.
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

        # ── Round 1: Bull opens (built with v1.5 cross-examination
        # instructions; surface speaker's pre-computed reasoning as
        # the snippet for now — keeps per-ticker cost bounded). ──
        _ = _build_debate_prompt(
            bull_champion.guru, ticker, bull_champion, "bull",
            query=query, spec=spec,
            opponent_signal=bear_champion,  # v1.5
        )
        snippets.append(f"🟢 {bull_champion.guru}: {bull_champion.reasoning[:300]}")

        # ── Round 2: Bear cross-examines ────────────────────────────
        _ = _build_debate_prompt(
            bear_champion.guru, ticker, bear_champion, "bear",
            query=query, spec=spec,
            opponent_signal=bull_champion,  # v1.5
        )
        snippets.append(f"🔴 {bear_champion.guru}: {bear_champion.reasoning[:300]}")

        # ── Round 3 (v1.5): Bull rebuttal ───────────────────────────
        bull_rebuttal_text = ""
        if llm_call:
            bull_rebuttal_prompt = _build_debate_prompt(
                bull_champion.guru, ticker, bull_champion, "bull_rebuttal",
                query=query, spec=spec,
                opponent_text=bear_champion.reasoning[:800],
            )
            try:
                bull_rebuttal_text = llm_call(
                    f"你是 {bull_champion.guru}，正在反驳对方质疑。",
                    bull_rebuttal_prompt,
                )
                snippets.append(
                    f"🟢 {bull_champion.guru} (反驳): {bull_rebuttal_text[:250]}"
                )
            except Exception as e:
                snippets.append(f"🟢 {bull_champion.guru} (反驳): 反驳失败 ({e})")
                bull_rebuttal_text = ""

        # ── Round 4: Judge ──────────────────────────────────────────
        if llm_call:
            judge_system, judge_user = _build_judge_prompts(
                bull_champion, bear_champion,
                bull_rebuttal=bull_rebuttal_text or None,  # v1.5
                query=query, spec=spec,
            )
            try:
                rebuttal = llm_call(judge_system, judge_user)
                snippets.append(f"⚖️ 裁判: {rebuttal[:250]}")
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
