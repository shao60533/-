"""Production-bug regression: SNDK analysis stored ``signal=Hold`` even
though ``trade_decision`` opened with ``最终评级：Sell（卖出）``. The
v1.16 extractor is required to recognise Chinese final-rating phrasing
and English ``Final Rating:`` plain prose so the detail page badge
matches the report body.
"""

from __future__ import annotations

import pytest

from stock_trading_system.agents.iterative.signal_extractor import (
    extract_trade_action,
)


# ── Chinese 最终评级 ── ────────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("最终评级：Sell（卖出）", "Sell"),
    ("最终评级：Buy（买入）", "Buy"),
    ("最终评级：Hold（持有）", "Hold"),
    ("最终交易决策：Sell（卖出）", "Sell"),
    ("最终交易决策：买入", "Buy"),
    ("最终决策: 持有", "Hold"),
    ("最终建议：卖出", "Sell"),
    # Production SNDK shape — body opens with the verdict, draft proposal
    # earlier in the section uses "Hold" but the final rating overrides.
    (
        "Hold for further validation might be considered, but...\n\n"
        "最终评级：Sell（卖出）\n"
        "最终交易决策：Sell（卖出）",
        "Sell",
    ),
])
def test_chinese_final_rating(text, expected):
    assert extract_trade_action(text) == expected


# ── English Final Rating: plain prose ────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("Final Rating: Sell", "Sell"),
    ("Final Decision: Buy", "Buy"),
    ("Final Action: Hold", "Hold"),
    ("Final Recommendation: SELL", "Sell"),
    # Bold mid-prose still wins as a last resort (no `Final` prefix).
    ("All considered, **SELL**.", "Sell"),
])
def test_english_plain_final_rating(text, expected):
    assert extract_trade_action(text) == expected


# ── Bold-only Chinese fallback ───────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("综合考虑，建议 **卖出**。", "Sell"),
    ("**买入** 是更稳妥的选择。", "Buy"),
    ("**持有** 等待信号", "Hold"),
])
def test_bold_chinese(text, expected):
    assert extract_trade_action(text) == expected


# ── Negative cases — no false positives on prose mentions ────────────────


@pytest.mark.parametrize("text", [
    "可考虑卖出风险大的标的",   # bare 卖出 in prose — not bold, not 最终
    "buy-side analysts are bullish",  # bare buy
    "holding period of three months",  # bare hold
    "",
    None,
])
def test_no_bare_keyword_false_positive(text):
    assert extract_trade_action(text) is None


# ── SNDK end-to-end: full body of the production trade_decision ──────────


def test_sndk_production_body():
    """Simplified version of the actual SNDK trade_decision payload that
    triggered the report. The body includes a draft "Hold" earlier and a
    final Chinese verdict — extractor must return Sell."""
    body = """
    Bull case argues for accumulation; bear case warns of margin
    compression. We provisionally consider Hold for further validation,
    but the latest pricing pressure tips the balance.

    最终评级：Sell（卖出）
    最终交易决策：Sell（卖出）

    Reasoning: ...
    """
    assert extract_trade_action(body) == "Sell"
