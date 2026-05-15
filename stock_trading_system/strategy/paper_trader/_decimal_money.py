"""Decimal-money helpers for the paper-trade simulator.

hardening-iteration-v1 P2.6 step-1: this module is the canonical
container for the Decimal arithmetic paper-trade will adopt. The
feature flag ``config["paper_trade"]["decimal"]`` controls whether
the simulator/order_engine actually route through these helpers
(step-2 wiring) or stay on float (current behaviour, default).

Why Decimal:

* Cash accumulation today uses ``float``: ``cash += shares * price``.
  After 1000 buy/sell loops on the same ticker the residual cash
  drifts by ~$0.005 because (a) 0.1 has no exact binary float
  representation and (b) commission/slippage products compound the
  error. Reports look wrong by a few cents which erodes trust.
* Decimal pins the rounding mode to ``ROUND_HALF_EVEN`` and uses
  base-10 arithmetic; 1000 round trips end at the analytically-correct
  cash value bit-for-bit.

What stays float (per design §3.3): percentages, weights, return
ratios. Those don't accumulate and the float speed/expressivity
matters more than the rounding-mode discipline.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from typing import Any


# Two-decimal cents for cash, PnL, commission. Tighter precisions
# don't help with US equity (penny-tick) and would just inflate the
# on-disk size.
CASH_QUANTIZE = Decimal("0.01")


def _ensure_context_precision() -> None:
    """Decimal's default precision (28) is fine, but ROUND_HALF_EVEN
    is not the default rounding mode. Bind it once at import."""
    ctx = getcontext()
    ctx.rounding = ROUND_HALF_EVEN


_ensure_context_precision()


def money(value: Any) -> Decimal:
    """Coerce a number (float / int / str / Decimal) to a 2-decimal
    Decimal in cents. Used at every boundary where a float crosses
    into the Decimal arithmetic core."""
    if isinstance(value, Decimal):
        return value.quantize(CASH_QUANTIZE)
    # Round-trip through str so a float like 0.1 lands as Decimal('0.1')
    # rather than Decimal('0.10000000000000000555...')
    return Decimal(str(value)).quantize(CASH_QUANTIZE)


def money_or_zero(value: Any) -> Decimal:
    """Like ``money()`` but maps None / "" / 0 to Decimal('0.00')."""
    if value in (None, ""):
        return CASH_QUANTIZE - CASH_QUANTIZE  # exact zero
    return money(value)


def is_decimal_paper_enabled(config: dict | None) -> bool:
    """Read the P2.6 feature flag. Defaults to False so existing
    paper-trade callers stay on the float code path until step-2."""
    if not config:
        return False
    pt = config.get("paper_trade") or {}
    return bool(pt.get("decimal", False))
