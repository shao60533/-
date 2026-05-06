"""paper-trade v1.5: trade-semantic validation in plan_parser._normalize.

Locks the contract that BUY plans cannot ship an exit_stop priced
*above* the reference price (which would trigger an immediate
profit-side stop the moment any bar prints below it). The pre-fix
flow would silently save such an order to ``planned_orders`` and the
order_engine would then close the open position on the same day.

Reference price priority is exercised: explicit ``current_price``
wins; falls back to entry zone midpoint, then advice entry-range
midpoint.
"""

from __future__ import annotations

from stock_trading_system.strategy.paper_trader.plan_parser import (
    _normalize, _resolve_reference_price, _validate_exit_level,
)


# ── _resolve_reference_price ────────────────────────────────────────


def test_reference_price_prefers_current_price_over_advice():
    advice = {"entry_price_low": 100, "entry_price_high": 110}
    ref = _resolve_reference_price(orders=[], advice=advice,
                                    current_price=190.0)
    assert ref == 190.0


def test_reference_price_falls_back_to_entry_zone_midpoint():
    orders = [{
        "type": "entry_initial",
        "trigger": {"kind": "breakout_retest", "zone_low": 200, "zone_high": 220},
    }]
    ref = _resolve_reference_price(orders=orders, advice=None, current_price=None)
    assert ref == 210.0


def test_reference_price_uses_advice_when_no_zone():
    advice = {"entry_price_low": 50, "entry_price_high": 60}
    ref = _resolve_reference_price(orders=[], advice=advice, current_price=None)
    assert ref == 55.0


def test_reference_price_returns_none_when_no_signal():
    ref = _resolve_reference_price(orders=[], advice=None, current_price=None)
    assert ref is None


# ── _validate_exit_level ────────────────────────────────────────────


def test_validate_long_stop_above_ref_is_rejected():
    order = {
        "type": "exit_stop",
        "trigger": {"kind": "price_below", "price": 202.49},
    }
    skip = _validate_exit_level(order, ref=190.0,
                                 rating_long=True, rating_short=False)
    assert skip is not None
    assert "invalid_stop_above_ref" in skip


def test_validate_long_stop_below_ref_is_kept():
    order = {
        "type": "exit_stop",
        "trigger": {"kind": "price_below", "price": 184.0},
    }
    skip = _validate_exit_level(order, ref=190.0,
                                 rating_long=True, rating_short=False)
    assert skip is None


def test_validate_long_target_below_ref_is_rejected():
    order = {
        "type": "exit_target",
        "trigger": {"kind": "price_above", "price": 175.0},
    }
    skip = _validate_exit_level(order, ref=190.0,
                                 rating_long=True, rating_short=False)
    assert skip is not None
    assert "invalid_target_below_ref" in skip


def test_validate_long_target_above_ref_is_kept():
    order = {
        "type": "exit_target",
        "trigger": {"kind": "price_above", "price": 220.0},
    }
    skip = _validate_exit_level(order, ref=190.0,
                                 rating_long=True, rating_short=False)
    assert skip is None


def test_validate_pattern_trigger_passes_through():
    """trailing_ma / breakout_retest / time_stop / immediate triggers
    don't carry a comparable ``price`` field; semantic validation
    must not reject them."""
    for kind in ("trailing_ma", "breakout_retest", "time_stop", "immediate"):
        order = {"type": "exit_stop", "trigger": {"kind": kind}}
        skip = _validate_exit_level(order, ref=190.0,
                                     rating_long=True, rating_short=False)
        assert skip is None, f"pattern trigger {kind!r} must pass through"


# ── _normalize end-to-end ───────────────────────────────────────────


def test_normalize_drops_buy_stop_above_current_price():
    """Production regression: NVDA at $190, LLM extracted stop at $202.49.
    Pre-fix the order shipped to planned_orders and triggered the
    same day. Post-fix it MUST be dropped + recorded in dropped_orders."""
    plan = {
        "rating": "BUY",
        "thesis": "buy thesis",
        "orders": [
            {
                "type": "entry_initial",
                "pct_target_total": 0.10,
                "trigger": {"kind": "immediate"},
                "desc": "build base",
            },
            {
                "type": "exit_stop",
                "pct_target_total": 0.0,
                "trigger": {"kind": "price_below", "price": 202.49},
                "desc": "stop loss",
            },
        ],
    }
    out = _normalize(plan, signal="BUY", advice=None, current_price=190.0)
    types = [o["type"] for o in out["orders"]]
    assert types == ["entry_initial"], (
        f"expected only entry_initial to survive; got {types}"
    )
    dropped = out.get("dropped_orders") or []
    assert len(dropped) == 1
    assert dropped[0]["type"] == "exit_stop"
    assert "invalid_stop_above_ref" in dropped[0]["skip_reason"]


def test_normalize_keeps_valid_buy_stop_below_current_price():
    plan = {
        "rating": "BUY",
        "thesis": "ok",
        "orders": [
            {
                "type": "entry_initial", "pct_target_total": 0.10,
                "trigger": {"kind": "immediate"}, "desc": "",
            },
            {
                "type": "exit_stop", "pct_target_total": 0.0,
                "trigger": {"kind": "price_below", "price": 184.0},
                "desc": "",
            },
            {
                "type": "exit_target", "pct_target_total": 0.0,
                "trigger": {"kind": "price_above", "price": 220.0},
                "desc": "",
            },
        ],
    }
    out = _normalize(plan, signal="BUY", advice=None, current_price=190.0)
    types = [o["type"] for o in out["orders"]]
    assert types == ["entry_initial", "exit_stop", "exit_target"]
    assert "dropped_orders" not in out


def test_normalize_no_ref_price_passes_everything():
    """Without a reference price we can't validate — must not break
    existing flows that have no current_price + no advice."""
    plan = {
        "rating": "BUY", "thesis": "x",
        "orders": [
            {
                "type": "exit_stop", "pct_target_total": 0.0,
                "trigger": {"kind": "price_below", "price": 999.0},
                "desc": "",
            },
        ],
    }
    out = _normalize(plan, signal="BUY", advice=None, current_price=None)
    assert len(out["orders"]) == 1
    assert "dropped_orders" not in out


def test_normalize_pct_target_total_is_clamped_to_fraction():
    """0..1 fraction contract preserved: 50 → 0.5, not 50%."""
    plan = {
        "rating": "BUY", "thesis": "",
        "orders": [
            {
                "type": "entry_initial", "pct_target_total": 50,
                "trigger": {"kind": "immediate"}, "desc": "",
            },
        ],
    }
    out = _normalize(plan, signal="BUY", advice=None, current_price=None)
    assert out["orders"][0]["pct_target_total"] == 0.5
