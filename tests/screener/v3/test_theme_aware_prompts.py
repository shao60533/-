"""Theme-aware guru prompt + roundtable + post-processor regression.

Locks v1.23 contract:
1. ``_build_theme_instruction`` renders both ``query`` and ``filter_spec``
   verbatim and includes the ``theme_fit`` requirement + the explicit
   storage / cloud-storage carve-outs.
2. ``BaseGuruAgent._llm_reason`` injects the instruction into the
   SystemMessage with the right key phrases.
3. ``roundtable._build_debate_prompt(query, spec)`` includes the user
   query and the three theme-fit questions.
4. ``_enforce_theme_fit`` caps total_score and downgrades signal when
   the LLM emitted a low theme_fit sub-analysis.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_trading_system.screener.v3.guru_agents.base import (
    BaseGuruAgent,
    GuruSignal,
    SubAnalysis,
    _build_theme_instruction,
    _enforce_theme_fit,
)
from stock_trading_system.screener.v3.roundtable import _build_debate_prompt


# ── 1. _build_theme_instruction ─────────────────────────────────────────

def test_theme_instruction_renders_query_and_spec_verbatim():
    inst = _build_theme_instruction(
        query="存储龙头股",
        spec={"themes": ["DRAM", "NAND"], "sectors": ["Semiconductors"]},
    )
    assert "存储龙头股" in inst
    assert "DRAM" in inst
    assert "Semiconductors" in inst


def test_theme_instruction_requires_theme_fit_subanalysis():
    inst = _build_theme_instruction(query="存储龙头股", spec={})
    assert "theme_fit" in inst
    # Cap rules must be mentioned so the LLM internalises them.
    assert "theme_fit < 4" in inst
    assert "theme_fit < 2" in inst


def test_theme_instruction_includes_required_storage_carveout():
    inst = _build_theme_instruction(query="存储龙头股", spec={})
    # Spec section 7 rule 10 — exact ticker examples.
    for required in ("MU", "WDC", "STX", "SNDK"):
        assert required in inst
    for forbidden in ("BRK-B", "JPM", "V", "MA", "PG", "WMT", "UNH"):
        assert forbidden in inst, f"{forbidden} missing from forbidden list"
    # Cloud carve-out must be explicit.
    assert "云存储" in inst
    for cloud in ("AMZN", "MSFT", "GOOGL"):
        assert cloud in inst


def test_theme_instruction_constrains_leader_to_user_theme():
    inst = _build_theme_instruction(query="存储龙头股", spec={})
    assert "龙头股" in inst
    # The contract is theme-internal leader, NOT market-cap leader.
    assert "用户指定主题/行业内的龙头" in inst or "主题/行业内的龙头" in inst
    assert "全市场市值龙头" in inst


# ── 2. _llm_reason injects the theme instruction into SystemMessage ─────

def test_llm_reason_system_message_carries_theme_instruction():
    """We don't actually call an LLM — we patch the chat model so the
    SystemMessage emitted by ``_llm_reason`` is captured and asserted.
    Verifies four spec phrases."""
    captured: dict = {}

    class _StubStructured:
        def invoke(self, messages):
            captured["messages"] = messages
            return GuruSignal(
                guru="buffett", ticker="AAPL", signal="neutral",
                confidence=0.5, reasoning="stub",
                sub_analyses=[SubAnalysis(
                    name="theme_fit", score=5.0, details="ok",
                )],
                total_score=50.0,
            )

    class _StubChat:
        def with_structured_output(self, _schema):
            return _StubStructured()

        def invoke(self, messages):  # pragma: no cover — should hit structured path
            captured["messages"] = messages
            return MagicMock(content='{"guru":"buffett","ticker":"AAPL","signal":"neutral","confidence":0.5,"reasoning":"x","sub_analyses":[],"key_metrics":{},"total_score":50}')

    agent = BaseGuruAgent()
    agent.name = "buffett"
    # Patch _get_chat_model on the instance only — keeps the BaseGuruAgent
    # class clean and avoids leaking into other tests.
    agent._get_chat_model = lambda ctx: _StubChat()  # type: ignore[method-assign]

    agent._llm_reason(
        system_prompt="你是 Warren Buffett。",
        user_prompt="分析 AAPL",
        ticker="AAPL",
        context={
            "provider": "qwen", "config": {},
            "nl_query": "存储龙头股",
            "filter_spec": {
                "themes": ["DRAM"], "sectors": ["Semiconductors"],
            },
        },
    )

    sys_text = captured["messages"][0].content
    # Spec phrases that must reach the model verbatim.
    assert "存储龙头股" in sys_text
    assert "theme_fit" in sys_text
    assert "用户指定主题/行业内的龙头" in sys_text or "主题/行业内的龙头" in sys_text
    # FilterSpec dict echoed.
    assert "DRAM" in sys_text


# ── 3. _build_debate_prompt anchors to query + spec ─────────────────────

def test_debate_prompt_includes_query_and_three_questions():
    sig = GuruSignal(
        guru="buffett", ticker="MU", signal="bullish",
        confidence=0.8, reasoning="MU 是 DRAM 龙头",
        sub_analyses=[], total_score=78.0,
    )
    prompt = _build_debate_prompt(
        "buffett", "MU", sig, "bull",
        query="存储龙头股", spec={"themes": ["DRAM"]},
    )
    assert "存储龙头股" in prompt
    # Three theme-fit questions per spec section 10.
    assert "是否直接符合用户查询主题" in prompt
    assert "主题内的龙头" in prompt
    assert "主题匹配" in prompt
    # Stance label.
    assert "看多" in prompt


def test_debate_prompt_offtheme_query_still_includes_query_field():
    sig = GuruSignal(
        guru="buffett", ticker="AAPL", signal="bullish",
        confidence=0.7, reasoning="护城河强",
        sub_analyses=[], total_score=72.0,
    )
    prompt = _build_debate_prompt(
        "buffett", "AAPL", sig, "bull",
        query="美股大盘龙头", spec={},
    )
    assert "美股大盘龙头" in prompt
    # The 3-question structure applies to every debate, themed or not.
    assert "是否直接符合用户查询主题" in prompt


# ── 4. _enforce_theme_fit cap rules ─────────────────────────────────────

def _signal(theme_fit: float, signal_value: str = "bullish",
            total: float = 80.0) -> GuruSignal:
    return GuruSignal(
        guru="buffett", ticker="AAPL", signal=signal_value,
        confidence=0.8, reasoning="x",
        sub_analyses=[
            SubAnalysis(name="fundamental", score=8.0, details=""),
            SubAnalysis(name="theme_fit", score=theme_fit, details=""),
        ],
        total_score=total,
    )


def test_enforce_theme_fit_caps_total_when_fit_low():
    """theme_fit < 4 → total_score ≤ 60 and bullish becomes neutral."""
    out = _enforce_theme_fit(_signal(theme_fit=3.0, total=85.0), context={})
    assert out.total_score <= 60.0
    assert out.signal == "neutral"


def test_enforce_theme_fit_blocks_bullish_when_fit_very_low():
    """theme_fit < 2 → total_score ≤ 45 and bullish becomes bearish."""
    out = _enforce_theme_fit(_signal(theme_fit=1.0, total=90.0), context={})
    assert out.total_score <= 45.0
    assert out.signal == "bearish"


def test_enforce_theme_fit_no_change_when_fit_high():
    """theme_fit ≥ 4 → no change."""
    sig = _signal(theme_fit=8.0, total=82.0)
    out = _enforce_theme_fit(sig, context={})
    assert out.total_score == 82.0
    assert out.signal == "bullish"


def test_enforce_theme_fit_skips_when_no_theme_fit_subanalysis():
    """LLM that didn't emit a theme_fit slot → no cap (defensive — we
    don't want to retroactively penalise legacy outputs)."""
    sig = GuruSignal(
        guru="buffett", ticker="AAPL", signal="bullish",
        confidence=0.8, reasoning="x",
        sub_analyses=[SubAnalysis(name="fundamental", score=8.0, details="")],
        total_score=85.0,
    )
    out = _enforce_theme_fit(sig, context={})
    assert out is sig  # exact same instance — no copy


def test_enforce_theme_fit_does_not_upgrade_neutral_to_bullish():
    """Sanity: low theme_fit should never RAISE a signal."""
    out = _enforce_theme_fit(
        _signal(theme_fit=3.0, signal_value="neutral", total=50.0),
        context={},
    )
    assert out.signal == "neutral"


def test_enforce_theme_fit_low_neutral_still_caps_total():
    out = _enforce_theme_fit(
        _signal(theme_fit=3.0, signal_value="neutral", total=85.0),
        context={},
    )
    assert out.total_score <= 60.0
