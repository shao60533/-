"""normalize_state_to_text turns TradingAgents state dicts into clean
Markdown so neither the analysis_history column nor the rendering LLM
prompt ever sees ``"{'judge_decision': '...'}"`` Python repr."""

from __future__ import annotations

import pytest

from stock_trading_system.agents.rendering.state_normalizer import (
    normalize_state_to_text,
)


# ── pass-through cases ──────────────────────────────────────────────────

def test_string_passthrough():
    assert normalize_state_to_text("已是字符串") == "已是字符串"


def test_none_returns_empty():
    assert normalize_state_to_text(None) == ""


def test_empty_dict_returns_empty():
    assert normalize_state_to_text({}, kind="investment_debate") == ""


# ── investment_debate ───────────────────────────────────────────────────

def test_investment_debate_renders_chinese_headings():
    state = {
        "judge_decision": "建议增持，看多方更有说服力。",
        "history": "Bull: ... Bear: ...",
        "bull_history": "AI 龙头估值合理。",
        "bear_history": "估值偏高。",
        "current_response": "Bull: 最后一轮回应。",
        "count": 4,
    }
    out = normalize_state_to_text(state, kind="investment_debate")
    # Chinese section headings appear, count is dropped.
    assert "## 裁判判定" in out
    assert "## 看多方陈述" in out
    assert "## 看空方陈述" in out
    # Python dict repr signature must NOT be present.
    assert "{'judge_decision'" not in out
    assert "'bull_history'" not in out
    # Body text preserved.
    assert "建议增持" in out
    assert "AI 龙头估值合理。" in out


def test_investment_debate_drops_empty_subfields():
    state = {
        "judge_decision": "结论。",
        "history": "",
        "bull_history": None,
        "bear_history": "  ",
        "count": 0,
    }
    out = normalize_state_to_text(state, kind="investment_debate")
    assert "## 裁判判定" in out
    assert "## 辩论历程" not in out
    assert "## 看多方陈述" not in out
    assert "## 看空方陈述" not in out


# ── risk_debate ─────────────────────────────────────────────────────────

def test_risk_debate_renders_three_stances():
    state = {
        "judge_decision": "整体风险中性。",
        "aggressive_history": "激进方观点。",
        "conservative_history": "保守方观点。",
        "neutral_history": "中立方观点。",
        "history": "完整历史略。",
        "count": 6,
        "latest_speaker": "Aggressive",
    }
    out = normalize_state_to_text(state, kind="risk_debate")
    assert "## 风控总判定" in out
    assert "## 激进派陈述" in out
    assert "## 保守派陈述" in out
    assert "## 中立派陈述" in out
    # latest_speaker is meta, should be dropped.
    assert "latest_speaker" not in out
    assert "Aggressive" not in out


# ── trade_decision ──────────────────────────────────────────────────────

def test_trade_decision_dict_renders():
    state = {
        "decision": "BUY",
        "reasoning": "AI 业务支撑估值。",
        "position_suggestion": "5-10%",
        "stop_loss": "$365",
        "take_profit": "$440",
        "time_horizon": "3-6 个月",
    }
    out = normalize_state_to_text(state, kind="trade_decision")
    assert "## 最终决策" in out
    assert "## 推理过程" in out
    assert "## 仓位建议" in out
    assert "{'decision'" not in out


def test_trade_decision_string_passes_through():
    """Trader normally returns a Markdown blob — preserve it verbatim."""
    text = "## 决策\n\nFINAL TRANSACTION PROPOSAL: **BUY**\n\n推荐买入。"
    assert normalize_state_to_text(text, kind="trade_decision") == text


# ── unknown kind / unknown keys ─────────────────────────────────────────

def test_generic_kind_renders_arbitrary_keys():
    state = {"foo": "bar", "baz": "qux"}
    out = normalize_state_to_text(state, kind="generic")
    assert "## foo" in out and "bar" in out
    assert "## baz" in out and "qux" in out
    assert "{'foo'" not in out


def test_unknown_subfield_appended_under_raw_key():
    """A new field added by upstream TradingAgents must not silently
    disappear — it falls through under its own heading."""
    state = {
        "judge_decision": "ok",
        "future_field": "新字段内容",
    }
    out = normalize_state_to_text(state, kind="investment_debate")
    assert "## 裁判判定" in out
    assert "## future_field" in out
    assert "新字段内容" in out


# ── invariants for analysis_history storage ─────────────────────────────

@pytest.mark.parametrize(
    "kind", ["investment_debate", "risk_debate", "trade_decision"],
)
def test_no_python_dict_repr_pattern(kind):
    """The single highest-impact regression to lock down: no matter what
    weird state shape a future TradingAgents version emits, our output
    must not look like ``{'key': '...'}`` to the user."""
    weird_state = {
        "judge_decision": "{'looks': 'like dict'}",  # adversarial inner string
        "history": "ok",
        "extra": {"nested": "value"},
    }
    out = normalize_state_to_text(weird_state, kind=kind)
    # The OUTPUT framing must not start with `{'…': …`. Internal strings
    # (which legitimately contain dict-like text from upstream) are not our
    # concern — the framing is.
    assert not out.lstrip().startswith("{'")
    assert "## " in out  # at least one Markdown heading present
