"""screener-v3 v1.5 — roundtable cross-examination tests.

Pins the contract:
* Round 1 (bull) prompt embeds own evidence + opponent fingerprint.
* Round 2 (bear) prompt forces speaker to cross-examine bull numbers.
* Round 3 (bull_rebuttal) prompt forces a binary stance, forbids the
  "双方都有道理" weasel phrase, caps at 200 chars.
* Judge prompt has the 5 required items (theme_fit / leader / winner +
  verbatim evidence / reversal condition / no fence-sitting).
* run_roundtable adds the (反驳) snippet when the ticker has both
  sides AND llm_call is provided.
"""

from __future__ import annotations

import asyncio

from stock_trading_system.screener.v3.guru_agents.base import (
    GuruSignal, SubAnalysis,
)
from stock_trading_system.screener.v3.roundtable import (
    _build_debate_prompt,
    _build_judge_prompts,
    run_roundtable,
)


def _sig(guru: str, ticker: str, signal: str, conf: float = 0.7,
         score: float = 65, reasoning: str = "默认推理",
         sub: list | None = None) -> GuruSignal:
    return GuruSignal(
        guru=guru, ticker=ticker, signal=signal, confidence=conf,
        reasoning=reasoning, sub_analyses=sub or [],
        key_metrics={}, total_score=score,
    )


def test_bull_prompt_includes_own_evidence_and_opponent_brief():
    bull = _sig(
        "buffett", "AAPL", "bullish", reasoning="护城河强 ROE 22%",
        sub=[SubAnalysis(name="moat", score=8, details="持续 5 年 ROE 22%")],
    )
    bear = _sig(
        "burry", "AAPL", "bearish", reasoning="估值过高",
        sub=[SubAnalysis(name="valuation", score=3, details="PE 35")],
    )
    prompt = _build_debate_prompt(
        "buffett", "AAPL", bull, "bull",
        query="科技龙头", opponent_signal=bear,
    )
    # Speaker's own evidence must be quotable from the prompt.
    assert "moat" in prompt or "ROE 22%" in prompt
    # Opponent's identity + weakest sub-analysis surface so the
    # speaker can flag them in their thesis.
    assert "burry" in prompt
    assert "valuation" in prompt or "PE 35" in prompt
    # Explicit instruction to quote at least one number.
    assert "quote" in prompt or "引用" in prompt


def test_bear_prompt_demands_cross_examine_bull_numbers():
    bull = _sig("buffett", "AAPL", "bullish", reasoning="ROE 22%")
    bear = _sig("burry", "AAPL", "bearish", reasoning="PE 35")
    prompt = _build_debate_prompt(
        "burry", "AAPL", bear, "bear",
        query="科技龙头", opponent_signal=bull,
    )
    # The cross-examination instruction must be present somewhere.
    assert (
        "cross-examine" in prompt
        or "你引用的" in prompt
        or "正方" in prompt
    )


def test_bull_rebuttal_prompt_demands_explicit_stance():
    bull = _sig("buffett", "AAPL", "bullish")
    prompt = _build_debate_prompt(
        "buffett", "AAPL", bull, "bull_rebuttal",
        opponent_text="你的 ROE 22% 是 1 年数据不算护城河",
    )
    # Forced binary endpoint — no fence-sitting.
    assert "维持 bullish" in prompt
    assert "下调到 neutral" in prompt
    assert "200 字" in prompt
    # The forbidden phrase appears in the prompt so the LLM knows
    # exactly what's banned.
    assert "双方都有道理" in prompt


def test_judge_prompts_demand_5_items():
    bull = _sig("buffett", "AAPL", "bullish", reasoning="A")
    bear = _sig("burry", "AAPL", "bearish", reasoning="B")
    sys, _usr = _build_judge_prompts(
        bull, bear, bull_rebuttal="C", query="科技龙头",
    )
    assert "5 项" in sys or "5项" in sys
    # Reversal condition (item 4) must be required.
    assert "反转条件" in sys or "改变结论" in sys
    # Verbatim quote requirement (item 3).
    assert (
        "verbatim" in sys.lower()
        or "verbatim quote" in sys.lower()
        or "引号包起" in sys
    )
    # Forbidden phrases listed explicitly.
    assert "双方都有道理" in sys


def test_judge_prompts_include_rebuttal_when_present():
    bull = _sig("buffett", "AAPL", "bullish", reasoning="A")
    bear = _sig("burry", "AAPL", "bearish", reasoning="B")
    _sys, usr = _build_judge_prompts(
        bull, bear, bull_rebuttal="REBUTTAL_TEXT",
    )
    # User-message must carry the rebuttal so the judge can score it.
    assert "REBUTTAL_TEXT" in usr


def test_run_roundtable_emits_round3_snippet_when_contested():
    """When llm_call is provided AND a ticker has both bullish and
    bearish gurus, snippets must contain the (反驳) line."""
    bull = _sig("buffett", "AAPL", "bullish", reasoning="A")
    bear = _sig("burry", "AAPL", "bearish", reasoning="B")
    calls = []

    def fake_llm(system: str, user: str) -> str:
        calls.append((system, user))
        return "我维持 bullish 因为 ROE 22% 是 5 年中位数不是单年数据"

    results = asyncio.run(run_roundtable(
        {"AAPL": [bull, bear]},
        llm_call=fake_llm,
        query="科技龙头",
    ))
    snippets = results["AAPL"].debate_snippets
    assert any("反驳" in s for s in snippets), (
        f"Expected (反驳) snippet in {snippets}"
    )
    # Two LLM calls expected: rebuttal + judge.
    assert len(calls) >= 2, (
        f"Expected at least 2 LLM calls (rebuttal + judge), got {len(calls)}"
    )
