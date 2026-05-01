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

# Match ``Final Rating: Sell`` / ``Final Decision: Buy`` (English text).
# No bold required — these are the LLM's plain-prose summaries.
_FINAL_RATING_RE = re.compile(
    r"Final\s+(?:Rating|Decision|Action|Recommendation|Proposal)\s*[:：]\s*"
    r"\*{0,2}(BUY|SELL|HOLD)\*{0,2}",
    re.IGNORECASE,
)

# Match Chinese final-rating phrasing — ``最终评级：Sell（卖出）``,
# ``最终交易决策：买入``, ``最终决策: 持有``. The Chinese verb may be
# followed by an English-keyword parenthetical or stand alone.
_CN_FINAL_RE = re.compile(
    r"最终(?:评级|决策|交易决策|建议|交易建议|动作)\s*[:：]\s*"
    r"\*{0,2}\s*(?:(BUY|SELL|HOLD)|(买入|卖出|持有))",
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

# Last-resort match: a Chinese verb in bold (``**卖出**``). Same "must be
# bolded" guard so the words don't trigger off prose like "可考虑买入".
_CN_BOLD_RE = re.compile(r"\*\*\s*(买入|卖出|持有)\s*\*\*")

_ACTION_TITLE = {"BUY": "Buy", "SELL": "Sell", "HOLD": "Hold"}
_CN_ACTION_TO_EN = {"买入": "BUY", "卖出": "SELL", "持有": "HOLD"}


def extract_trade_action(text_or_dict) -> str | None:
    """Parse the final trader action ("Buy" / "Sell" / "Hold") from a
    ``trade_decision`` string or the ``final_trade_decision`` dict.

    Returns ``None`` when no clean signal is recoverable — the caller
    should then fall back to whatever ``graph.process_signal`` produced
    (typically OVERWEIGHT / UNDERWEIGHT, which this function intentionally
    doesn't try to disambiguate from BUY / SELL).

    Match order — earlier patterns win, then within a pattern the LAST
    occurrence wins so a section that opens with a draft proposal but
    closes with a corrected one resolves to the corrected one:

    1. ``FINAL TRANSACTION PROPOSAL: **BUY/SELL/HOLD**`` (English canonical)
    2. ``Final Rating: Sell`` / ``Final Decision: Buy`` (English plain prose)
    3. ``最终评级：Sell（卖出）`` / ``最终交易决策：买入`` (Chinese)
    4. ``**BUY**`` / ``**SELL**`` / ``**HOLD**`` bolded English token
    5. ``**买入**`` / ``**卖出**`` / ``**持有**`` bolded Chinese token

    Falls through to ``None`` when none match. We deliberately do NOT
    scan plain prose for plain "buy" / "sell" / "hold" / "卖出" / "买入"
    / "持有" — those words appear in non-actionable context all the
    time ("buy-side analysts", "可考虑卖出风险大的标的"). Bolded or
    "FINAL"/"最终"-prefixed mentions are the only safe signals.
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

    # Each tier scans independently; within a tier we keep the LAST
    # match so post-correction text wins over draft proposals earlier
    # in the body. Tiers 1-3 are tried in order and we stop at the
    # first tier that produced any match (mixing tiers is a class of
    # silent contradiction we'd rather not paper over).
    for pattern in (_FINAL_PROPOSAL_RE, _FINAL_RATING_RE):
        last: str | None = None
        for m in pattern.finditer(text):
            last = m.group(1).upper()
        if last is not None:
            return _ACTION_TITLE[last]

    # Chinese final-rating: groups are (english_word_or_None, cn_word_or_None).
    last_cn: str | None = None
    for m in _CN_FINAL_RE.finditer(text):
        if m.group(1):
            last_cn = m.group(1).upper()
        elif m.group(2):
            last_cn = _CN_ACTION_TO_EN[m.group(2)]
    if last_cn is not None:
        return _ACTION_TITLE[last_cn]

    # Bold-only standalone fallback (English then Chinese).
    last_bold: str | None = None
    for m in _BOLD_ACTION_RE.finditer(text):
        last_bold = m.group(1).upper()
    if last_bold is not None:
        return _ACTION_TITLE[last_bold]

    for m in _CN_BOLD_RE.finditer(text):
        last_bold = _CN_ACTION_TO_EN[m.group(1)]
    if last_bold is not None:
        return _ACTION_TITLE[last_bold]

    return None
