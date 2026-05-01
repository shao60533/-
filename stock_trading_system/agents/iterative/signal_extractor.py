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


# ── Canonical trade-action extractor (v1.20) ─────────────────────────────
#
# Single source of truth for "what did the trader actually decide". Used
# by the analyzer to override ``result.signal`` and by the detail DTO to
# detect / report drift between the stored signal and the trade-decision
# text. ``signal`` historically came from ``graph.process_signal`` which
# is a separate LLM call and occasionally disagreed with the trader's
# explicit ``FINAL TRANSACTION PROPOSAL: **X**`` line — that's the
# "顶部 Hold, 决策正文 Sell" bug this function exists to kill.

# Match ``FINAL TRANSACTION PROPOSAL: **BUY**`` (and minor variants:
# bare without **, leading/trailing whitespace, mixed case).
_FINAL_PROPOSAL_RE = re.compile(
    r"FINAL\s+TRANSACTION\s+PROPOSAL\s*:\s*\*{0,2}(BUY|SELL|HOLD)\*{0,2}",
    re.IGNORECASE,
)

# Last-resort match: a ``**BUY**`` / ``**SELL**`` / ``**HOLD**`` token
# anywhere in the body. We deliberately require the bold markdown so a
# lower-case mention of "buy" inside prose ("we recommend a buy bias")
# doesn't trigger a false positive.
_BOLD_ACTION_RE = re.compile(
    r"\*\*\s*(BUY|SELL|HOLD)\s*\*\*",
    re.IGNORECASE,
)

_ACTION_TITLE = {"BUY": "Buy", "SELL": "Sell", "HOLD": "Hold"}


def extract_trade_action(text_or_dict) -> str | None:
    """Parse the final trader action ("Buy" / "Sell" / "Hold") from a
    ``trade_decision`` string or the ``final_trade_decision`` dict.

    Returns ``None`` when no clean signal is recoverable — the caller
    should then fall back to whatever ``graph.process_signal`` produced
    (typically OVERWEIGHT / UNDERWEIGHT, which this function intentionally
    doesn't try to disambiguate from BUY / SELL).

    Match order — last match wins so a section that opens with an
    intermediate proposal but closes with a corrected one resolves to the
    final one:

    1. ``FINAL TRANSACTION PROPOSAL: **BUY/SELL/HOLD**`` (canonical)
    2. ``**BUY**`` / ``**SELL**`` / ``**HOLD**`` bolded standalone token

    Falls through to ``None`` when neither pattern matches; we explicitly
    do NOT scan plain prose for the words "buy"/"sell"/"hold" because the
    same words appear in non-actionable context (e.g. "buy-side analysts",
    "sell-off risk", "holding period").
    """
    if text_or_dict is None:
        return None
    if isinstance(text_or_dict, dict):
        # ``final_trade_decision`` from TradingAgents is sometimes a dict
        # like ``{"messages": [...], "trade_decision": "..."}``. Try the
        # explicit text key first, then fall back to a JSON string of the
        # whole thing so any nested message body still gets scanned.
        text = (
            text_or_dict.get("trade_decision")
            or text_or_dict.get("final_trade_decision")
            or text_or_dict.get("content")
            or json.dumps(text_or_dict, ensure_ascii=False, default=str)
        )
    else:
        text = str(text_or_dict)
    text = text.strip()
    if not text:
        return None

    last_action: str | None = None
    for m in _FINAL_PROPOSAL_RE.finditer(text):
        last_action = m.group(1).upper()
    if last_action is not None:
        return _ACTION_TITLE[last_action]

    # No FINAL PROPOSAL — try bold standalone tokens. Same "last wins"
    # rule because trader memos sometimes include earlier draft proposals.
    for m in _BOLD_ACTION_RE.finditer(text):
        last_action = m.group(1).upper()
    if last_action is not None:
        return _ACTION_TITLE[last_action]
    return None
