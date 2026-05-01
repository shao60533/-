"""Convert TradingAgents state dicts into clean Markdown text.

The graph emits ``investment_debate_state`` and ``risk_debate_state`` as
nested dicts with sub-fields (``judge_decision``, ``bull_history``,
``aggressive_history`` …). Calling ``str(d)`` against them produces the
infamous ``"{'judge_decision': '...', 'history': '...'}"`` Python repr
that leaks into both the analysis_history column and the LLM prompt
fed to the rendering extractor — neither place can render that as
human-friendly Chinese.

This module exposes a single entry point :func:`normalize_state_to_text`
that returns Markdown-ish text suitable for both storage and prompts.
A non-dict input passes through (the worker may have already serialised
it). The function is intentionally lossless — every populated sub-field
appears in the output under a Chinese heading.
"""

from __future__ import annotations

from typing import Any


_INVESTMENT_DEBATE_FIELDS: list[tuple[str, str]] = [
    ("judge_decision",   "裁判判定"),
    ("history",          "辩论历程"),
    ("bull_history",     "看多方陈述"),
    ("bear_history",     "看空方陈述"),
    ("current_response", "最新发言"),
]

_RISK_DEBATE_FIELDS: list[tuple[str, str]] = [
    ("judge_decision",       "风控总判定"),
    ("history",              "辩论历程"),
    ("aggressive_history",   "激进派陈述"),
    ("conservative_history", "保守派陈述"),
    ("neutral_history",      "中立派陈述"),
    ("risky_history",        "激进派陈述"),
    ("safe_history",         "保守派陈述"),
]

_TRADE_DECISION_FIELDS: list[tuple[str, str]] = [
    ("decision",            "最终决策"),
    ("reasoning",           "推理过程"),
    ("position_suggestion", "仓位建议"),
    ("stop_loss",           "止损位"),
    ("take_profit",         "止盈位"),
    ("time_horizon",        "时间周期"),
]


def _render_sections(value: dict[str, Any],
                      schema: list[tuple[str, str]]) -> str:
    """Render the known fields under ``## <Chinese heading>`` sections.

    Unknown / extra fields are appended verbatim (key as heading) so
    upstream additions never get silently dropped.
    """
    used: set[str] = set()
    parts: list[str] = []

    for key, heading in schema:
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        used.add(key)
        parts.append(f"## {heading}\n\n{text}")

    for key, raw in value.items():
        if key in used or key in {"count", "latest_speaker"}:
            continue
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        parts.append(f"## {key}\n\n{text}")

    return "\n\n".join(parts)


def normalize_state_to_text(value: Any, *, kind: str = "generic") -> str:
    """Return a Markdown-ish text for storage and LLM prompts.

    ``kind`` selects the field schema:

    * ``investment_debate`` — bull/bear debate state
    * ``risk_debate``       — three-stance risk state
    * ``trade_decision``    — trader's final decision dict (rare —
      normally a string)
    * ``generic``           — fallback that just renders ``str(value)``

    Non-dict inputs pass through unchanged (already a string, list of
    messages, ``None``, etc.). ``None`` / empty inputs return ``""`` so
    callers can ``or ""`` safely.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)
    if not value:
        return ""

    if kind == "investment_debate":
        rendered = _render_sections(value, _INVESTMENT_DEBATE_FIELDS)
    elif kind == "risk_debate":
        rendered = _render_sections(value, _RISK_DEBATE_FIELDS)
    elif kind == "trade_decision":
        rendered = _render_sections(value, _TRADE_DECISION_FIELDS)
    else:
        rendered = "\n\n".join(
            f"## {k}\n\n{str(v).strip()}"
            for k, v in value.items()
            if v not in (None, "")
        )

    return rendered or ""
