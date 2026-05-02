"""screener-v3 v1.5 — per-guru prompt personalisation tests.

Locks the contract:
* every guru declares 3 anti_patterns + 2-3 decision_style + non-empty
  evidence_demands;
* anti-pattern phrases are unique across gurus (each is identity-
  specific, not a templated default);
* signature self-questions match the public persona (Buffett 10-year
  hold, Lynch 10-year-old test, Munger invert, Graham 33% margin);
* the three new prompt blocks render only when fields are populated;
* reasoning_format is now 4 sections including the v1.5 reversal-
  condition §4;
* legacy SYSTEM_PROMPT theme clauses (the ones that overlapped with
  v1.3 _build_theme_instruction) have been removed from all 14 files.
"""

from __future__ import annotations

from stock_trading_system.screener.v3.guru_agents.base import (
    _build_anti_pattern_block,
    _build_decision_style_block,
    _build_evidence_demand_block,
    _build_reasoning_format_instruction,
)
from stock_trading_system.screener.v3.guru_agents.buffett import BuffettAgent
from stock_trading_system.screener.v3.guru_agents.graham import GrahamAgent
from stock_trading_system.screener.v3.guru_agents.lynch import LynchAgent
from stock_trading_system.screener.v3.guru_agents.munger import MungerAgent
from stock_trading_system.screener.v3.guru_agents.fisher import FisherAgent
from stock_trading_system.screener.v3.guru_agents.burry import BurryAgent
from stock_trading_system.screener.v3.guru_agents.ackman import AckmanAgent
from stock_trading_system.screener.v3.guru_agents.wood import WoodAgent
from stock_trading_system.screener.v3.guru_agents.druckenmiller import DruckenmillerAgent
from stock_trading_system.screener.v3.guru_agents.damodaran import DamodaranAgent
from stock_trading_system.screener.v3.guru_agents.pabrai import PabraiAgent
from stock_trading_system.screener.v3.guru_agents.taleb import TalebAgent
from stock_trading_system.screener.v3.guru_agents.marks import MarksAgent
from stock_trading_system.screener.v3.guru_agents.dalio import DalioAgent


ALL_GURUS = [
    BuffettAgent(), GrahamAgent(), LynchAgent(), MungerAgent(),
    FisherAgent(), BurryAgent(), AckmanAgent(), WoodAgent(),
    DruckenmillerAgent(), DamodaranAgent(), PabraiAgent(), TalebAgent(),
    MarksAgent(), DalioAgent(),
]


def test_each_guru_has_three_anti_patterns():
    for g in ALL_GURUS:
        assert len(g.anti_patterns) == 3, (
            f"{g.name} should have exactly 3 anti_patterns, "
            f"got {len(g.anti_patterns)}"
        )


def test_each_guru_has_two_or_three_decision_styles():
    for g in ALL_GURUS:
        assert 2 <= len(g.decision_style) <= 3, (
            f"{g.name} should have 2-3 decision_style items, "
            f"got {len(g.decision_style)}"
        )


def test_each_guru_has_evidence_demands():
    for g in ALL_GURUS:
        assert g.evidence_demands.strip(), (
            f"{g.name} evidence_demands empty"
        )


def test_anti_patterns_unique_across_gurus():
    """No two gurus share an exact anti-pattern phrase (each is identity-
    specific). This guards against future copy-paste regressions where
    we add a guru and forget to write fresh anti-patterns."""
    seen: dict[str, str] = {}
    for g in ALL_GURUS:
        for ap in g.anti_patterns:
            assert ap not in seen, (
                f"Duplicate anti_pattern: {ap!r} "
                f"({seen.get(ap)} vs {g.name})"
            )
            seen[ap] = g.name


def test_decision_style_includes_signature_self_questions():
    """The four named gurus (B/G/L/M) must keep their public-persona
    signature phrases. Pre-v1.5 every guru's reasoning lead was the
    same theme-mismatch line; this test pins the personas back."""
    bf = next(g for g in ALL_GURUS if g.name == "buffett")
    assert any("10 年" in s for s in bf.decision_style)
    lc = next(g for g in ALL_GURUS if g.name == "lynch")
    assert any("10 岁孩子" in s for s in lc.decision_style)
    mg = next(g for g in ALL_GURUS if g.name == "munger")
    assert any("invert" in s.lower() or "反向" in s for s in mg.decision_style)
    gh = next(g for g in ALL_GURUS if g.name == "graham")
    assert any("33%" in s or "安全边际" in s for s in gh.decision_style)


def test_anti_pattern_block_renders_when_present():
    block = _build_anti_pattern_block(["pattern A", "pattern B"])
    assert "pattern A" in block
    assert "pattern B" in block
    # Tells the LLM how to log a hit so aggregators can detect it later.
    assert "anti_pattern_hit" in block


def test_anti_pattern_block_empty_when_none():
    assert _build_anti_pattern_block([]) == ""


def test_decision_style_block_renders():
    block = _build_decision_style_block(["我会问：'X？'"])
    assert "X" in block
    # Reminder to embed the self-question in quotes inside reasoning §1.
    assert "引号" in block


def test_evidence_demand_block_renders():
    block = _build_evidence_demand_block("ROE 5 年中位数")
    assert "ROE 5 年中位数" in block
    # Tells the LLM how to log missing data so it can't fabricate.
    assert "evidence_gap" in block


def test_evidence_demand_block_empty_when_blank():
    assert _build_evidence_demand_block("") == ""
    assert _build_evidence_demand_block("   ") == ""


def test_reasoning_format_has_four_sections():
    instr = _build_reasoning_format_instruction("X")
    # 4 段落 markers — the v1.5 upgrade from 3.
    assert "段一" in instr
    assert "段二" in instr
    assert "段三" in instr
    assert "段四" in instr
    # 段四 must require a falsifiable reversal condition.
    assert "反转" in instr or "改变我的结论" in instr


def test_system_prompt_lacks_legacy_theme_clause():
    """v1.5 deletes the trailing 3-sentence theme block from every
    SYSTEM_PROMPT (it duplicated v1.3's _build_theme_instruction and
    diluted the model's attention)."""
    leaked_phrase = "在本系统中，你的任务不是单独判断"
    for g in ALL_GURUS:
        assert leaked_phrase not in g.SYSTEM_PROMPT, (
            f"{g.name} SYSTEM_PROMPT still has v1.3 legacy theme clause"
        )
