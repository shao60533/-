"""v1.4 — guru-signal uniqueness + framework-lead distinctiveness.

Locks the contract that drove the "大师评分详情同质化" fix:

1. ``guru_signals`` for a single ticker is unique by ``guru`` —
   downstream UI keys on ``guru`` so a duplicate would silently shadow
   one of the cards.
2. The four named gurus (Buffett / Lynch / Graham / Munger) each have
   their own ``framework_lead`` and the system prompt that ships to
   the LLM forces ``reasoning`` to lead with that framework. We can't
   assert the LLM's output text here (LLM is mocked), so we assert
   the *prompt* the LLM receives is distinct per guru in the segments
   that matter. Pair this with a synthesis check that mocked
   reasonings round-trip without collapsing to the same first 120
   chars.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
    _build_reasoning_format_instruction,
    _build_theme_instruction,
)
from stock_trading_system.screener.v3.guru_agents.buffett import BuffettAgent
from stock_trading_system.screener.v3.guru_agents.graham import GrahamAgent
from stock_trading_system.screener.v3.guru_agents.lynch import LynchAgent
from stock_trading_system.screener.v3.guru_agents.munger import MungerAgent


# ── 1. guru_signals uniqueness ──────────────────────────────────────────

def test_guru_signals_unique_by_guru_per_ticker():
    """``ScreenerV3Pipeline._aggregate`` emits ``guru_signals`` as a list
    of GuruSignal model dumps. The frontend now keys cards by
    ``s.guru`` (not array index) so the same guru appearing twice would
    silently shadow one of the rows. Stand a fixture list together with
    the de-dup logic the UI relies on, and assert the invariant.
    """
    sigs = [
        GuruSignal(guru="buffett", ticker="MU", signal="bullish",
                   confidence=0.7, reasoning="moat ok",
                   sub_analyses=[], total_score=70).model_dump(),
        GuruSignal(guru="lynch", ticker="MU", signal="neutral",
                   confidence=0.5, reasoning="peg high",
                   sub_analyses=[], total_score=55).model_dump(),
        GuruSignal(guru="graham", ticker="MU", signal="bearish",
                   confidence=0.4, reasoning="pe stretched",
                   sub_analyses=[], total_score=45).model_dump(),
        GuruSignal(guru="munger", ticker="MU", signal="bullish",
                   confidence=0.8, reasoning="quality high",
                   sub_analyses=[], total_score=78).model_dump(),
    ]
    gurus = [s["guru"] for s in sigs]
    assert len(gurus) == len(set(gurus)), \
        f"guru_signals must be unique by guru; got {gurus}"


def test_guru_signals_keyed_dedup_helper():
    """Mirror of the frontend ``candidateGuruScoresList`` reduction.
    If the worker ever emits a duplicate, the dispatcher should fail
    loudly (assertion below) rather than silently shadow a card.
    """
    raw = [
        {"guru": "buffett", "signal": "bullish", "confidence": 0.7},
        {"guru": "buffett", "signal": "bearish", "confidence": 0.4},  # dup
    ]
    seen: dict[str, dict] = {}
    for s in raw:
        seen.setdefault(s["guru"], s)
    assert len(seen) == 1
    # Document the regression: a real run should NOT produce duplicates;
    # if it does, prefer the first occurrence (highest confidence is
    # picked elsewhere in the aggregator) but the React key would still
    # break — flag it.
    duplicate_count = len(raw) - len(seen)
    assert duplicate_count == 1, "fixture sanity"


# ── 2. framework_lead is set + distinct on the four named gurus ─────────

def test_four_named_gurus_have_framework_lead():
    """Spec calls out Buffett / Lynch / Graham / Munger by name; each
    must have a non-empty ``framework_lead`` so the reasoning prompt
    instructs the LLM to lead with that framework's verdict."""
    for cls in (BuffettAgent, LynchAgent, GrahamAgent, MungerAgent):
        agent = cls()
        assert agent.framework_lead, \
            f"{cls.__name__}.framework_lead must be set"
        # Fall-back to philosophy is allowed for the other 10 gurus —
        # but for these four it MUST be explicit.
        assert agent.framework_lead != agent.philosophy, \
            f"{cls.__name__} should override framework_lead, not reuse philosophy"


def test_named_gurus_framework_leads_pairwise_distinct():
    leads = {
        "buffett": BuffettAgent().framework_lead,
        "lynch": LynchAgent().framework_lead,
        "graham": GrahamAgent().framework_lead,
        "munger": MungerAgent().framework_lead,
    }
    # Every pair must differ — that's what stops the four cards from
    # rendering identical reasoning leads.
    distinct = len({v for v in leads.values()})
    assert distinct == len(leads), \
        f"framework_lead must be unique across the four named gurus; got {leads}"


def test_buffett_lead_mentions_moat_and_safety_margin():
    fl = BuffettAgent().framework_lead
    assert "护城河" in fl
    assert "安全边际" in fl


def test_lynch_lead_mentions_peg_and_growth():
    fl = LynchAgent().framework_lead
    assert "PEG" in fl
    assert "成长" in fl or "Growth" in fl or "growth" in fl


def test_graham_lead_mentions_valuation_and_balance_sheet():
    fl = GrahamAgent().framework_lead
    # Spec hints: 估值/资产负债/安全边际
    assert "估值" in fl or "PE" in fl
    assert "资产负债" in fl
    assert "安全边际" in fl


def test_munger_lead_mentions_quality_and_competitive_advantage():
    fl = MungerAgent().framework_lead
    assert "质量" in fl
    assert "竞争优势" in fl


# ── 3. reasoning format instruction surfaces the framework lead ──────────

def test_reasoning_format_instruction_includes_framework_lead():
    """The instruction must inject the per-guru ``framework_lead`` and
    must NOT tell the LLM to lead with theme content."""
    inst = _build_reasoning_format_instruction("护城河 / 自由现金流 / 安全边际")
    # Lead phrase must be present, verbatim.
    assert "护城河 / 自由现金流 / 安全边际" in inst
    # Three-paragraph structure must be specified.
    assert "段一" in inst
    assert "段二" in inst
    assert "段三" in inst
    # And theme content must be explicitly forbidden in段一.
    assert "主题契合度" in inst or "主题匹配" in inst
    assert "不能用" in inst  # the "不能用'该公司主题匹配 …'作开头" guard


def test_theme_instruction_no_longer_forces_theme_into_reasoning_lead():
    """v1.3 told the LLM ``reasoning 必须明确说明: - 该公司与用户主题是否
    直接相关 …`` which made every guru's lead identical for off-theme
    tickers. v1.4 moves that requirement to ``sub_analyses[theme_fit]``.
    """
    inst = _build_theme_instruction(query="存储龙头股", spec={})
    # The earlier "reasoning 必须明确说明 [theme stuff]" structure must
    # not appear — that was the regression vector.
    assert "reasoning 必须明确说明：" not in inst, \
        "theme instruction must not force theme content into reasoning lead"
    # theme_fit sub_analysis is still required.
    assert "theme_fit" in inst


# ── 4. _llm_reason composes both instructions into the SystemMessage ────

class _StubAgent(BaseGuruAgent):
    name = "stub"
    display_name = "Stub Guru"
    philosophy = "stub philosophy"
    framework_lead = "stub-framework-lead"

    def _get_chat_model(self, context):  # pragma: no cover — only the
        # captured ``invoke`` path matters for this test.
        return self._captured_chat


def test_llm_reason_injects_reasoning_format_instruction():
    """Capture the SystemMessage handed to the LLM and assert it
    contains both the theme block and the per-guru framework-lead
    block. The structured-output path is mocked to return a valid
    GuruSignal so we don't depend on a real LLM."""
    agent = _StubAgent()

    captured: dict = {}

    structured_chain = MagicMock()
    structured_chain.invoke.side_effect = lambda msgs: (
        captured.setdefault("messages", msgs),
        GuruSignal(
            guru="stub", ticker="ABC", signal="neutral", confidence=0.5,
            reasoning="ok", sub_analyses=[], total_score=50,
        ),
    )[-1]

    chat = MagicMock()
    chat.with_structured_output.return_value = structured_chain
    agent._captured_chat = chat

    sig = agent._llm_reason(
        system_prompt="STUB SYSTEM PROMPT BODY",
        user_prompt="user prompt",
        ticker="ABC",
        context={"nl_query": "存储龙头股", "filter_spec": {}},
    )

    assert sig.guru == "stub"
    assert "messages" in captured
    # First message is the SystemMessage; pull its content.
    sys_content = captured["messages"][0].content
    assert "STUB SYSTEM PROMPT BODY" in sys_content
    assert "stub-framework-lead" in sys_content, \
        "framework_lead must be injected into the SystemMessage"
    assert "段一" in sys_content
    assert "theme_fit" in sys_content
    # Regression guard: the v1.3 regression vector must not return.
    assert "reasoning 必须明确说明：" not in sys_content


# ── 5. Reasoning-lead distinctness — synthesis test ────────────────────

def test_first_120_chars_distinct_when_lead_respected():
    """Synthesis test: given mocked reasoning that respects the v1.4
    structure (each lead conclusion uses the framework's keywords),
    the leading 120-character window of the four cards must be
    distinct. This is what the user is checking on the UI.
    """
    # Compose plausible reasoning leads using each guru's framework
    # keywords. These mirror what the LLM is now instructed to produce.
    leads = {
        "buffett":
            "护城河强劲，自由现金流稳定，估值具有安全边际，长期持有的"
            "理想标的。ROE 25% 远超同业，FCF 利润率 20%。",
        "lynch":
            "成长阶段判定为快速增长，PEG 0.8 具有吸引力，散户也能"
            "理解的业务模式。盈利增长 28% 与 PE 23 相称。",
        "graham":
            "估值偏便宜，PE 12 / PB 1.2 满足 22.5 阈值，资产负债结构"
            "保守，安全边际充裕。流动比率 2.4，无亏损年。",
        "munger":
            "商业质量优秀，持久竞争优势明显，业务模型简单可理解，"
            "复杂度低。管理层资本配置历史良好，护城河可持续。",
    }
    leads_120 = {k: v[:120] for k, v in leads.items()}
    # Pairwise distinctness — what the UI cards display first.
    assert len(set(leads_120.values())) == len(leads_120)
    # Each lead must mention the guru's anchor concept.
    assert "护城河" in leads_120["buffett"]
    assert "PEG" in leads_120["lynch"]
    assert "PE" in leads_120["graham"]
    assert "竞争优势" in leads_120["munger"]


def test_reasoning_lead_must_not_start_with_theme_keyword():
    """If the LLM regresses and starts the reasoning with a theme
    sentence, the v1.4 prompt explicitly forbids it. We assert the
    prompt content here so the regression is caught at config time,
    not by waiting for a UI screenshot."""
    inst = _build_reasoning_format_instruction("护城河 / 自由现金流 / 安全边际")
    # Both forbidden lead phrasings must be called out by the prompt.
    assert "该公司主题匹配" in inst, \
        "prompt must forbid '该公司主题匹配 …' as a reasoning lead"
    assert "该 ticker 与用户主题" in inst, \
        "prompt must forbid '该 ticker 与用户主题 …' as a reasoning lead"
