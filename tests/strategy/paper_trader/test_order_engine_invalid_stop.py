"""paper-trade v1.5: order_engine evaluate_day must skip exit_stop
orders whose price is >= the long position's avg_cost or >= today's
close. Even when plan_parser semantic validation didn't catch it
(e.g. legacy planned_orders rows imported pre-v1.5), the engine
itself MUST refuse to close-at-profit a long position.

Also locks the new ``_collect_plan_levels`` / ``_validated_stop`` /
``_validated_target`` helpers that pin plan-level risk bounds onto
new open_trades.
"""

from __future__ import annotations

from stock_trading_system.strategy.paper_trader.order_engine import (
    _collect_plan_levels, _validated_stop, _validated_target,
)


# ── _collect_plan_levels ────────────────────────────────────────────


def test_collect_plan_levels_picks_first_explicit_stop_and_target():
    orders = [
        {
            "order_type": "exit_stop",
            "trigger": {"kind": "trailing_ma", "period": 20},
        },
        {
            "order_type": "exit_stop",
            "trigger": {"kind": "price_below", "price": 184.0},
        },
        {
            "order_type": "exit_stop",
            "trigger": {"kind": "price_below", "price": 170.0},
        },
        {
            "order_type": "exit_target",
            "trigger": {"kind": "price_above", "price": 220.0},
        },
    ]
    levels = _collect_plan_levels(orders)
    # First explicit price-based stop wins; trailing_ma is skipped
    # because it has no comparable price.
    assert levels["stop"] == 184.0
    assert levels["target"] == 220.0


def test_collect_plan_levels_returns_none_when_only_pattern_triggers():
    orders = [
        {"order_type": "exit_stop",
         "trigger": {"kind": "trailing_ma", "period": 20}},
        {"order_type": "exit_target",
         "trigger": {"kind": "time_stop", "months": 6}},
    ]
    levels = _collect_plan_levels(orders)
    assert levels == {"stop": None, "target": None}


# ── _validated_stop ─────────────────────────────────────────────────


def test_validated_stop_accepts_stop_below_entry():
    assert _validated_stop(184.0, entry=190.0, fill=190.0,
                            otype="entry_initial") == 184.0


def test_validated_stop_rejects_stop_above_entry():
    """Production regression: stop=202 with entry=190 would close on
    the first bar that prints any price < 202 (i.e. immediately)."""
    assert _validated_stop(202.0, entry=190.0, fill=190.0,
                            otype="entry_initial") is None


def test_validated_stop_rejects_stop_equal_to_entry():
    assert _validated_stop(190.0, entry=190.0, fill=190.0,
                            otype="entry_initial") is None


def test_validated_stop_rejects_when_below_fill_only():
    """Both entry and fill must be above the stop — otherwise the
    add-on event would fire instantly."""
    assert _validated_stop(195.0, entry=200.0, fill=190.0,
                            otype="entry_add") is None


def test_validated_stop_returns_none_for_non_entry_otype():
    """Stops are only pinned when an entry creates the open_trade."""
    assert _validated_stop(180.0, entry=190.0, fill=190.0,
                            otype="exit_stop") is None


def test_validated_stop_handles_missing_refs_gracefully():
    """No entry/fill at all → trust the plan-level price (best effort)."""
    assert _validated_stop(184.0, entry=None, fill=None,
                            otype="entry_initial") == 184.0


# ── _validated_target ───────────────────────────────────────────────


def test_validated_target_accepts_target_above_entry():
    assert _validated_target(220.0, entry=190.0, fill=190.0,
                              otype="entry_initial") == 220.0


def test_validated_target_rejects_target_below_entry():
    assert _validated_target(180.0, entry=190.0, fill=190.0,
                              otype="entry_initial") is None


def test_validated_target_rejects_target_equal_to_max_ref():
    assert _validated_target(195.0, entry=195.0, fill=190.0,
                              otype="entry_initial") is None
