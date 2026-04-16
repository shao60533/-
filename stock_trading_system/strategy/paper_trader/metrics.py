"""Metrics calculation for paper-trade sessions."""

from __future__ import annotations

import math
from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.metrics")


def compute_session_metrics(
    trades: list[dict],
    equity: list[dict],
    start_capital: float,
) -> dict:
    """Compute summary metrics from completed trades + daily equity.

    Returns dict with:
        total_return, total_return_pct, annualized_return_pct,
        num_trades, num_winning, num_losing, win_rate_pct,
        avg_hold_days, avg_win_pct, avg_loss_pct,
        max_drawdown_pct, sharpe_ratio, final_value,
        benchmark_return_pct (if benchmark present)
    """
    if not equity:
        return {
            "total_return": 0, "total_return_pct": 0, "annualized_return_pct": 0,
            "num_trades": 0, "num_winning": 0, "num_losing": 0, "win_rate_pct": 0,
            "avg_hold_days": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
            "max_drawdown_pct": 0, "sharpe_ratio": 0,
            "final_value": start_capital, "benchmark_return_pct": None,
        }

    final_value = float(equity[-1]["total_value"])
    total_return = final_value - start_capital
    total_return_pct = (total_return / start_capital) * 100 if start_capital else 0

    # Annualized return
    days = max(len(equity), 1)
    years = days / 252.0 if days >= 20 else None
    if years and years > 0 and start_capital > 0:
        annualized = ((final_value / start_capital) ** (1 / years) - 1) * 100
    else:
        annualized = total_return_pct

    # Trade-level stats
    closed = [t for t in trades if t.get("exit_date")]
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) <= 0]
    num_trades = len(closed)
    win_rate = (len(wins) / num_trades * 100) if num_trades else 0

    hold_days = [t.get("hold_days") or 0 for t in closed]
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0

    avg_win = sum(t.get("pnl_pct") or 0 for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl_pct") or 0 for t in losses) / len(losses) if losses else 0

    # Max drawdown (on equity curve)
    peak = float(equity[0]["total_value"])
    max_dd = 0.0
    for e in equity:
        v = float(e["total_value"])
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd

    # Sharpe (simple, daily returns, 0 risk-free)
    if len(equity) >= 2:
        returns = []
        for i in range(1, len(equity)):
            prev = float(equity[i - 1]["total_value"])
            cur = float(equity[i]["total_value"])
            if prev > 0:
                returns.append((cur - prev) / prev)
        sharpe = 0.0
        if returns:
            mean = sum(returns) / len(returns)
            var = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = math.sqrt(var) if var > 0 else 0
            if std > 0:
                sharpe = (mean / std) * math.sqrt(252)
    else:
        sharpe = 0.0

    # Benchmark return (if available)
    benchmark_pct = None
    if equity[0].get("benchmark_value") and equity[-1].get("benchmark_value"):
        b0 = float(equity[0]["benchmark_value"])
        bn = float(equity[-1]["benchmark_value"])
        if b0 > 0:
            benchmark_pct = round((bn / b0 - 1) * 100, 2)

    return {
        "total_return": round(total_return, 2),
        "total_return_pct": round(total_return_pct, 2),
        "annualized_return_pct": round(annualized, 2),
        "num_trades": num_trades,
        "num_winning": len(wins),
        "num_losing": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "avg_hold_days": round(avg_hold, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "final_value": round(final_value, 2),
        "benchmark_return_pct": benchmark_pct,
    }


def ticker_breakdown(trades: list[dict]) -> list[dict]:
    """Per-ticker aggregation of closed trades."""
    closed = [t for t in trades if t.get("exit_date")]
    by_ticker: dict = {}
    for t in closed:
        k = t["ticker"]
        by_ticker.setdefault(k, {"ticker": k, "trades": 0, "wins": 0,
                                 "total_pnl": 0.0, "total_pnl_pct": 0.0})
        b = by_ticker[k]
        b["trades"] += 1
        if (t.get("pnl") or 0) > 0:
            b["wins"] += 1
        b["total_pnl"] += t.get("pnl") or 0
        b["total_pnl_pct"] += t.get("pnl_pct") or 0
    out = list(by_ticker.values())
    for b in out:
        b["win_rate_pct"] = round(b["wins"] / b["trades"] * 100, 2) if b["trades"] else 0
        b["avg_pnl_pct"] = round(b["total_pnl_pct"] / b["trades"], 2) if b["trades"] else 0
        b["total_pnl"] = round(b["total_pnl"], 2)
        b["total_pnl_pct"] = round(b["total_pnl_pct"], 2)
    out.sort(key=lambda x: -x["total_pnl"])
    return out
