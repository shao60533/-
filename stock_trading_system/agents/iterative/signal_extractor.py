"""Extract directional signals from individual agent outputs.

Three extraction strategies:
- LLM:   4 analysts — ask qwen to classify as BULLISH/BEARISH/NEUTRAL
- Fixed: bull_researcher → BULLISH, bear_researcher → BEARISH
- Regex: trader — parse "FINAL TRANSACTION PROPOSAL: **BUY/SELL/HOLD**"
"""

from __future__ import annotations

import json
import re

from stock_trading_system.utils import get_logger

logger = get_logger("iterative.signal_extractor")

_SIGNAL_EXTRACTION_PROMPT = (
    "Extract the directional signal from this analyst report.\n"
    'Output exactly one JSON: {{"signal": "BULLISH" | "BEARISH" | "NEUTRAL"}}\n'
    "Report: {report_text}"
)

_VALID_SIGNALS = {"BULLISH", "BEARISH", "NEUTRAL"}


def extract_signal_llm(report_text: str, llm_call: callable) -> str:
    """Use an LLM to classify an analyst report as BULLISH/BEARISH/NEUTRAL.

    Args:
        report_text: The analyst report (truncated to 2000 chars internally).
        llm_call: A callable(system_prompt, user_prompt) -> str.

    Returns:
        One of BULLISH, BEARISH, NEUTRAL, or ERROR on failure.
    """
    if not report_text or not report_text.strip():
        return "NEUTRAL"

    truncated = report_text[:2000]
    prompt = _SIGNAL_EXTRACTION_PROMPT.format(report_text=truncated)

    try:
        raw = llm_call("You are a signal classifier.", prompt)
        # Try to parse JSON from response
        match = re.search(r'\{[^}]*"signal"\s*:\s*"([^"]+)"', raw)
        if match:
            signal = match.group(1).upper().strip()
            if signal in _VALID_SIGNALS:
                return signal
        # Fallback: look for signal keywords directly
        upper = raw.upper()
        for s in ("BULLISH", "BEARISH", "NEUTRAL"):
            if s in upper:
                return s
        logger.warning("Could not parse signal from LLM response: %s", raw[:200])
        return "NEUTRAL"
    except Exception as e:
        logger.error("LLM signal extraction failed: %s", e)
        return "ERROR"


def extract_signal_fixed(agent_id: str) -> str:
    """Return a fixed signal based on structural role.

    bull_researcher → BULLISH, bear_researcher → BEARISH.
    """
    mapping = {
        "bull_researcher": "BULLISH",
        "bear_researcher": "BEARISH",
    }
    return mapping.get(agent_id, "NEUTRAL")


def extract_signal_regex(trader_plan: str) -> str:
    """Parse trader output for BUY/SELL/HOLD via regex.

    Looks for patterns like "FINAL TRANSACTION PROPOSAL: **BUY**" or
    simple "BUY" / "SELL" / "HOLD" keywords.
    """
    if not trader_plan:
        return "NEUTRAL"

    text = trader_plan if isinstance(trader_plan, str) else str(trader_plan)

    # Pattern 1: "FINAL TRANSACTION PROPOSAL: **BUY**"
    match = re.search(
        r"FINAL\s+TRANSACTION\s+PROPOSAL\s*:\s*\*{0,2}(BUY|SELL|HOLD)\*{0,2}",
        text, re.IGNORECASE,
    )
    if match:
        action = match.group(1).upper()
        return _action_to_signal(action)

    # Pattern 2: standalone action keywords
    upper = text.upper()
    for action in ("BUY", "SELL", "HOLD"):
        if action in upper:
            return _action_to_signal(action)

    return "NEUTRAL"


def _action_to_signal(action: str) -> str:
    return {"BUY": "BULLISH", "SELL": "BEARISH", "HOLD": "NEUTRAL"}.get(
        action.upper(), "NEUTRAL"
    )
