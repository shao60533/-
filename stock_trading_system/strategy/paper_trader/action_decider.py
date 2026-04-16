"""Decide what to do from an AI advice + current position state.

Reads advice.action (strong signal), suggested_position_pct (target), and
entry range / stop / target. Falls back to signal string if advice missing.

Returns an Action dict:
    {
        "action": "open|add|reduce|close|reverse|hold|skipped|no_action",
        "target_shares": float | None,       # for open/add/reduce
        "target_position_pct": float | None, # desired % of total equity
        "skip_reason": str | None,
        "reason": str,                        # human-readable
    }
"""

from __future__ import annotations

# Normalized advice action bucket
_BUY_LIKE = {"BUY", "ADD", "ACCUMULATE", "OVERWEIGHT", "STRONG_BUY"}
_SELL_LIKE = {"SELL", "CLOSE", "EXIT", "UNDERWEIGHT", "STRONG_SELL"}
_REDUCE_LIKE = {"REDUCE", "TRIM", "LIGHTEN"}
_HOLD_LIKE = {"HOLD", "WAIT", "WATCH", "NEUTRAL", "OBSERVE"}

# Risk-warning keywords that demote a BUY to "待观察"
_WAIT_KEYWORDS = ("暂缓", "观望", "等待回调", "等待企稳", "急跌", "不建议追高",
                   "谨慎", "推迟", "暂不", "避免追涨", "wait", "pullback")


def decide_action(
    *,
    signal: str,
    advice: dict | None,
    current_price: float | None,
    current_shares: float,
    total_equity: float,
) -> dict:
    """Produce an Action dict given advice + state."""
    signal = (signal or "").upper()
    advice = advice or {}
    action_raw = (advice.get("action") or signal or "").upper()
    target_pct = advice.get("suggested_position_pct")
    if target_pct is not None:
        try:
            target_pct = float(target_pct)
            if target_pct > 1.0:  # stored as percent, normalize
                target_pct /= 100.0
        except (TypeError, ValueError):
            target_pct = None

    entry_low = advice.get("entry_price_low")
    entry_high = advice.get("entry_price_high")
    risk_warn = (advice.get("risk_warning") or "").lower()

    # ── Price range guard ────────────────────────────────────────────
    price_ok = True
    price_reason = None
    if current_price and entry_low and entry_high:
        try:
            lo, hi = float(entry_low), float(entry_high)
            if current_price < lo or current_price > hi:
                price_ok = False
                price_reason = (f"price {current_price:.2f} out of entry range "
                                f"{lo:.2f}-{hi:.2f}")
        except (TypeError, ValueError):
            pass

    # ── Risk-warning keyword demotion ────────────────────────────────
    demoted = any(kw in risk_warn for kw in _WAIT_KEYWORDS)

    # ── Buy-like ─────────────────────────────────────────────────────
    if action_raw in _BUY_LIKE:
        if not price_ok:
            return {"action": "skipped", "skip_reason": price_reason,
                    "reason": f"BUY 信号但 {price_reason}",
                    "target_shares": None, "target_position_pct": target_pct}
        if demoted:
            return {"action": "hold", "skip_reason": "risk_warning_wait",
                    "reason": "BUY 信号但风险提示含观望关键词，仅记录不下单",
                    "target_shares": None, "target_position_pct": target_pct}
        pct = target_pct if target_pct is not None else 0.10
        target_value = total_equity * pct
        price = current_price or entry_low or entry_high
        if not price or price <= 0:
            return {"action": "skipped", "skip_reason": "no_price",
                    "reason": "无有效成交价", "target_shares": None,
                    "target_position_pct": target_pct}
        target_shares = target_value / price
        if current_shares <= 0:
            return {"action": "open", "target_shares": target_shares,
                    "target_position_pct": pct,
                    "reason": f"开仓 {target_shares:.2f} 股 ({pct*100:.0f}% 目标仓位)",
                    "skip_reason": None}
        # Already holding — compare target vs current
        cur_pct = (current_shares * price) / total_equity if total_equity > 0 else 0
        if pct > cur_pct + 0.01:   # need to add
            delta_shares = target_shares - current_shares
            return {"action": "add", "target_shares": target_shares,
                    "target_position_pct": pct,
                    "reason": f"加仓至 {target_shares:.2f} 股 (+{delta_shares:.2f})",
                    "skip_reason": None}
        return {"action": "hold", "target_shares": current_shares,
                "target_position_pct": pct,
                "reason": f"BUY 信号，已达目标仓位 ({cur_pct*100:.1f}% vs {pct*100:.0f}%)，持有",
                "skip_reason": None}

    # ── Sell-like ────────────────────────────────────────────────────
    if action_raw in _SELL_LIKE:
        if current_shares <= 0:
            return {"action": "no_action", "target_shares": 0,
                    "target_position_pct": 0,
                    "reason": "SELL 信号但空仓，不开空", "skip_reason": "no_position"}
        return {"action": "close", "target_shares": 0,
                "target_position_pct": 0,
                "reason": f"平仓 {current_shares:.2f} 股", "skip_reason": None}

    # ── Reduce-like ──────────────────────────────────────────────────
    if action_raw in _REDUCE_LIKE:
        if current_shares <= 0:
            return {"action": "no_action", "target_shares": 0,
                    "target_position_pct": 0,
                    "reason": "REDUCE 信号但空仓", "skip_reason": "no_position"}
        pct = target_pct if target_pct is not None else 0.05
        price = current_price
        if not price or price <= 0:
            return {"action": "skipped", "skip_reason": "no_price",
                    "reason": "无有效成交价", "target_shares": None,
                    "target_position_pct": pct}
        target_value = total_equity * pct
        target_shares = max(0.0, target_value / price)
        if target_shares >= current_shares:
            return {"action": "hold", "target_shares": current_shares,
                    "target_position_pct": pct,
                    "reason": "REDUCE 目标 ≥ 当前仓位，保持", "skip_reason": None}
        return {"action": "reduce", "target_shares": target_shares,
                "target_position_pct": pct,
                "reason": f"减仓至 {target_shares:.2f} 股",
                "skip_reason": None}

    # ── Hold / Wait / Watch ──────────────────────────────────────────
    if action_raw in _HOLD_LIKE:
        return {"action": "hold", "target_shares": current_shares,
                "target_position_pct": target_pct,
                "reason": f"{action_raw} 信号，不下单仅记录", "skip_reason": None}

    # Unknown — record as hold
    return {"action": "hold", "target_shares": current_shares,
            "target_position_pct": target_pct,
            "reason": f"未识别 action={action_raw}，保持",
            "skip_reason": "unknown_action"}
