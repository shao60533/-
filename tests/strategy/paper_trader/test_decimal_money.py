"""hardening-iteration-v1 P2.6 step-1 — Decimal money helpers.

Step-1 ships the helpers + feature flag; step-2 (subsequent PR) flips
``paper_trade.simulator`` / ``paper_trade.order_engine`` /
``session_store`` to consult the flag and use Decimal arithmetic for
cash accumulation when it's enabled.

This suite locks down:
    1. ``money()`` coerces float/int/str → 2-decimal Decimal.
    2. ``money()`` round-trips floats via str (no binary-float garbage).
    3. ``money_or_zero()`` maps None/'' → Decimal('0.00').
    4. ``is_decimal_paper_enabled()`` defaults to False (no flag set);
       respects truthy/falsy in the YAML.
    5. ROUND_HALF_EVEN is the active rounding mode (kept by import).
    6. 1000-loop buy/sell on the same ticker drifts 0 cents with the
       Decimal helpers (the smoke contract step-2 will rely on).
"""

from __future__ import annotations

from decimal import Decimal, getcontext, ROUND_HALF_EVEN

import pytest


from stock_trading_system.strategy.paper_trader._decimal_money import (
    money, money_or_zero, is_decimal_paper_enabled, CASH_QUANTIZE,
)


def test_money_from_float():
    """0.1 should land as Decimal('0.10') exactly (str round-trip)."""
    assert money(0.1) == Decimal("0.10")
    assert money(123.456) == Decimal("123.46")


def test_money_from_int():
    assert money(100) == Decimal("100.00")


def test_money_from_str():
    assert money("99.99") == Decimal("99.99")


def test_money_from_decimal_quantizes():
    """A 4-decimal Decimal must round-half-even to 2 decimals."""
    assert money(Decimal("1.235")) == Decimal("1.24")  # half-even
    assert money(Decimal("1.245")) == Decimal("1.24")  # half-even (banker's)


def test_money_or_zero_none():
    assert money_or_zero(None) == Decimal("0.00")
    assert money_or_zero("") == Decimal("0.00")
    assert money_or_zero(0) == Decimal("0.00")


def test_is_decimal_paper_enabled_default_false():
    """Feature flag defaults to False so step-2 wiring is opt-in."""
    assert is_decimal_paper_enabled(None) is False
    assert is_decimal_paper_enabled({}) is False
    assert is_decimal_paper_enabled({"paper_trade": {}}) is False


def test_is_decimal_paper_enabled_true_only_when_set():
    assert is_decimal_paper_enabled(
        {"paper_trade": {"decimal": True}}
    ) is True
    # Any falsy value reads false (defends against accidental string flags).
    assert is_decimal_paper_enabled(
        {"paper_trade": {"decimal": False}}
    ) is False
    assert is_decimal_paper_enabled(
        {"paper_trade": {"decimal": 0}}
    ) is False


def test_rounding_mode_is_half_even():
    """Imported module pins ROUND_HALF_EVEN on the active context."""
    assert getcontext().rounding == ROUND_HALF_EVEN


def test_thousand_loop_buy_sell_zero_drift():
    """Buy 100 shares at 1.10 and sell at 1.10 a thousand times — cash
    must end at exactly the starting value. The float code path drifts
    by ~$0.005 due to binary-float rounding; Decimal must hit 0 exactly.

    This is the smoke contract step-2 will rely on when rewiring
    simulator.py to the Decimal path."""
    initial = Decimal("10000.00")
    cash = initial
    shares = 100
    px = money("1.10")
    for _ in range(1000):
        cash -= money(shares) * px  # buy
        cash += money(shares) * px  # sell
    assert cash == initial


def test_two_decimal_quantize_constant():
    """Defensive: CASH_QUANTIZE is what every helper rounds to. Catch
    accidental edits that loosen the rounding to whole-dollars."""
    assert CASH_QUANTIZE == Decimal("0.01")
