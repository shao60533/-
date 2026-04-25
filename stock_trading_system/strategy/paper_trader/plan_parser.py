"""Extract a structured multi-stage trading plan from an AI analysis.

Primary path: Qwen JSON mode with a few-shot schema prompt.
Fallback:     regex-based extraction of percentages, price levels, and keywords.
Last resort:  single immediate entry_initial using advice.suggested_position_pct.

The output plan shape is:
{
    "rating": "BUY" | "HOLD" | "SELL",
    "thesis": str,
    "holding_months_min": int | None,
    "holding_months_max": int | None,
    "orders": [
        {
            "type": "entry_initial" | "entry_add" | "exit_stop" | "exit_target" | "exit_trailing",
            "pct_target_total": float,  # 0..1 fraction of total equity
            "trigger": {
                "kind": "immediate" | "price_above" | "price_below" |
                        "breakout_retest" | "trailing_ma" | "time_stop",
                # kind-specific fields:
                "price": float,                         # for price_above / price_below
                "zone_low": float, "zone_high": float,   # for breakout_retest
                "period": int,                           # for trailing_ma (default 20)
                "months": int,                           # for time_stop
            },
            "desc": str,
        },
        ...
    ]
}
"""

from __future__ import annotations

import json
import re

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.plan_parser")

_PLAN_SCHEMA_PROMPT = """你是一位交易员，将 AI 分析报告的 executive_summary / trade_decision \
转换为结构化多阶段交易计划 JSON。

严格输出如下 schema（只输出 JSON，不要其它文字）：

{
  "rating": "BUY" | "HOLD" | "SELL",
  "thesis": "核心论点一句话",
  "holding_months_min": 整数或 null,
  "holding_months_max": 整数或 null,
  "orders": [
    {
      "type": "entry_initial" | "entry_add" | "exit_stop" | "exit_target" | "exit_trailing",
      "pct_target_total": 0..1 之间的小数（触发后的目标总仓位占比；平仓档位写 0）,
      "trigger": {
        "kind": "immediate" | "price_above" | "price_below" | "breakout_retest" | "trailing_ma" | "time_stop",
        // kind-specific:
        "price": 数字,                         // price_above / price_below
        "zone_low": 数字, "zone_high": 数字,    // breakout_retest（突破后回踩）
        "period": 整数,                        // trailing_ma（均线周期，默认 20）
        "months": 整数                         // time_stop
      },
      "desc": "人类可读描述"
    }
  ]
}

规则：
1. 如果文本说"初始以 X%-Y% 建仓"：生成 type=entry_initial, trigger.kind=immediate, pct_target_total=(X+Y)/200
2. 如果文本说"突破 A-B 美元回踩后加仓至 Z%"：生成 type=entry_add, trigger.kind=breakout_retest, zone_low=A, zone_high=B, pct_target_total=Z/100
3. 如果文本说"跌破 N 美元清仓/止损"：生成 type=exit_stop, trigger.kind=price_below, price=N, pct_target_total=0
4. 如果文本说"跟踪均线"或"移动跟踪机制"：生成 type=exit_trailing, trigger.kind=trailing_ma, period=20, pct_target_total=0
5. 如果文本说"投资周期 X-Y 个月"：填入 holding_months_min/max
6. 数字单位按文本本身（美元不换算）；比例一律 0..1
7. 至少生成 1 个 entry_initial；如果没明确止损，不要生成 exit_stop
8. SELL 报告：生成 type=exit_stop, trigger.kind=immediate, pct_target_total=0（立即清仓）
9. HOLD 报告：orders 数组为空

示例输入：
Rating: BUY
Executive Summary: 针对 NVDA 执行"克制型进攻"交易指令。初始以 10%-15% 资金建立底仓，若价格有效突破并回踩确认 200-210 美元阻力支撑带，则阶梯式加仓至总敞口 20% 上限。硬性风控线设定为 184 美元，跌破即无条件执行纪律性减仓。盈利保护采用中期均线移动跟踪机制。投资周期 3-6 个月。

示例输出：
{
  "rating": "BUY",
  "thesis": "克制型进攻：底仓 + 突破回踩加仓 + 硬性止损 + 均线跟踪",
  "holding_months_min": 3, "holding_months_max": 6,
  "orders": [
    {"type": "entry_initial", "pct_target_total": 0.125,
     "trigger": {"kind": "immediate"},
     "desc": "初始以 10-15% 资金建立底仓"},
    {"type": "entry_add", "pct_target_total": 0.20,
     "trigger": {"kind": "breakout_retest", "zone_low": 200, "zone_high": 210},
     "desc": "突破并回踩 200-210 → 加仓至 20%"},
    {"type": "exit_stop", "pct_target_total": 0.0,
     "trigger": {"kind": "price_below", "price": 184},
     "desc": "硬性止损：跌破 184"},
    {"type": "exit_trailing", "pct_target_total": 0.0,
     "trigger": {"kind": "trailing_ma", "period": 20},
     "desc": "中期均线跟踪止盈"}
  ]
}
"""


# ── Main entry ────────────────────────────────────────────────────────────

def extract_plan(analysis: dict, advice: dict | None,
                 qwen_provider=None) -> tuple[dict, str]:
    """Return (plan, parse_method) where parse_method ∈ {'llm','regex','fallback'}."""
    text = _collect_text(analysis)
    signal = (analysis.get("signal") or "").upper()

    if qwen_provider and getattr(qwen_provider, "_enabled", False):
        plan = _extract_via_llm(qwen_provider, text, signal)
        if plan and _is_valid(plan):
            return _normalize(plan, signal, advice), "llm"

    plan = _extract_via_regex(text, signal, advice)
    if plan and _is_valid(plan):
        return _normalize(plan, signal, advice), "regex"

    return _fallback_plan(signal, advice), "fallback"


# ── Text collector ────────────────────────────────────────────────────────

def _collect_text(ana: dict) -> str:
    parts = []
    # advice.reasoning is usually richest
    raw_advice = ana.get("advice_json")
    if raw_advice:
        try:
            a = json.loads(raw_advice) if isinstance(raw_advice, str) else raw_advice
            if a.get("reasoning"):
                parts.append(str(a["reasoning"]))
            if a.get("risk_warning"):
                parts.append("风险提示：" + str(a["risk_warning"]))
        except Exception:
            pass
    # trade_decision tends to contain the executive summary
    for k in ("trade_decision", "risk_assessment", "investment_debate"):
        v = ana.get(k)
        if v:
            parts.append(str(v))
    return "\n\n".join(parts)[:8000]   # hard cap


# ── LLM path ──────────────────────────────────────────────────────────────

def _extract_via_llm(provider, text: str, signal: str) -> dict | None:
    user_prompt = f"分析信号：{signal}\n\n原文：\n{text}\n\n请输出 JSON。"
    try:
        # Provider._call is private but stable; wrap defensively
        out = provider._call(_PLAN_SCHEMA_PROMPT, user_prompt)  # noqa: SLF001
    except Exception as e:
        logger.warning("LLM plan extract failed: %s", e)
        return None
    return out if isinstance(out, dict) else None


# ── Regex path ────────────────────────────────────────────────────────────

_RANGE_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*%")
_SINGLE_PCT = re.compile(r"(?:至|到|加仓至|目标|上限)\s*(\d+(?:\.\d+)?)\s*%")
_RANGE_DOLLAR = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*美?元")
_SINGLE_DOLLAR = re.compile(r"\$?\s*(\d{2,5}(?:\.\d+)?)\s*美?元")
_HOLDING_MONTHS = re.compile(r"(\d+)\s*[-~至到]\s*(\d+)\s*个?月")
_STOP_KEYS = ("跌破", "无条件", "清仓", "止损", "硬性", "风控线")
_TRAIL_KEYS = ("均线", "移动跟踪", "跟踪止盈", "trailing")


def _extract_via_regex(text: str, signal: str, advice: dict | None) -> dict | None:
    if not text:
        return None
    if signal == "HOLD":
        return {"rating": "HOLD", "thesis": "持有观望", "orders": []}
    if signal in ("SELL", "UNDERWEIGHT"):
        return {"rating": "SELL", "thesis": "减仓或清仓",
                "orders": [{"type": "exit_stop", "pct_target_total": 0.0,
                             "trigger": {"kind": "immediate"},
                             "desc": "立即清仓"}]}

    orders = []

    # Initial entry: "10%-15%"
    m = _RANGE_PCT.search(text)
    init_pct = 0.10
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        init_pct = (lo + hi) / 200.0
    orders.append({
        "type": "entry_initial", "pct_target_total": round(init_pct, 4),
        "trigger": {"kind": "immediate"},
        "desc": f"初始建仓 {init_pct*100:.1f}%",
    })

    # Add: look for "突破" + "X-Y" dollar range + "加仓至 Z%"
    if any(k in text for k in ("突破", "阶梯式加仓", "回踩")):
        dm = _RANGE_DOLLAR.search(text)
        if dm:
            lo_p, hi_p = float(dm.group(1)), float(dm.group(2))
            # Target total pct — look for "至 N%" or "上限 N%"
            target_pct = 0.20
            tm = _SINGLE_PCT.search(text)
            if tm:
                target_pct = float(tm.group(1)) / 100.0
            orders.append({
                "type": "entry_add",
                "pct_target_total": round(target_pct, 4),
                "trigger": {"kind": "breakout_retest",
                             "zone_low": lo_p, "zone_high": hi_p},
                "desc": f"突破并回踩 {lo_p}-{hi_p} → 加仓至 {target_pct*100:.0f}%",
            })

    # Stop loss
    if any(k in text for k in _STOP_KEYS):
        # First find "跌破 N" explicit
        stop_price = None
        m_below = re.search(r"跌破\s*\$?\s*(\d{2,5}(?:\.\d+)?)\s*美?元", text)
        if m_below:
            stop_price = float(m_below.group(1))
        elif advice and advice.get("stop_loss"):
            stop_price = float(advice["stop_loss"])
        if stop_price:
            orders.append({
                "type": "exit_stop", "pct_target_total": 0.0,
                "trigger": {"kind": "price_below", "price": stop_price},
                "desc": f"硬性止损：跌破 {stop_price:.2f}",
            })

    # Trailing MA
    if any(k in text for k in _TRAIL_KEYS):
        period = 20
        m_ma = re.search(r"MA\s*(\d+)|(\d+)\s*日均线", text)
        if m_ma:
            period = int(m_ma.group(1) or m_ma.group(2))
        orders.append({
            "type": "exit_trailing", "pct_target_total": 0.0,
            "trigger": {"kind": "trailing_ma", "period": period},
            "desc": f"跟踪止盈：收盘跌破 MA{period}",
        })

    # Holding period
    hmin = hmax = None
    m_hold = _HOLDING_MONTHS.search(text)
    if m_hold:
        hmin, hmax = int(m_hold.group(1)), int(m_hold.group(2))

    return {
        "rating": "BUY",
        "thesis": None,  # filled from analysis_history.executive_summary
        "holding_months_min": hmin, "holding_months_max": hmax,
        "orders": orders,
    }


# ── Fallback path ─────────────────────────────────────────────────────────

def _fallback_plan(signal: str, advice: dict | None) -> dict:
    signal = (signal or "").upper()
    if signal == "HOLD":
        return {"rating": "HOLD", "thesis": "持有观望", "orders": []}
    if signal in ("SELL", "UNDERWEIGHT"):
        return {"rating": "SELL", "thesis": "清仓",
                "orders": [{"type": "exit_stop", "pct_target_total": 0.0,
                             "trigger": {"kind": "immediate"}, "desc": "立即清仓"}]}

    advice = advice or {}
    pct = advice.get("suggested_position_pct") or 0.10
    if pct > 1:
        pct /= 100.0
    orders = [{"type": "entry_initial", "pct_target_total": float(pct),
                "trigger": {"kind": "immediate"},
                "desc": f"单档建仓 {float(pct)*100:.0f}%"}]
    if advice.get("stop_loss"):
        orders.append({"type": "exit_stop", "pct_target_total": 0.0,
                        "trigger": {"kind": "price_below",
                                     "price": float(advice["stop_loss"])},
                        "desc": f"止损 {float(advice['stop_loss']):.2f}"})
    if advice.get("take_profit"):
        orders.append({"type": "exit_target", "pct_target_total": 0.0,
                        "trigger": {"kind": "price_above",
                                     "price": float(advice["take_profit"])},
                        "desc": f"止盈 {float(advice['take_profit']):.2f}"})
    return {"rating": "BUY", "thesis": "fallback", "orders": orders}


# ── Validation & normalization ────────────────────────────────────────────

def _is_valid(plan: dict) -> bool:
    if not isinstance(plan, dict):
        return False
    if plan.get("rating") not in ("BUY", "HOLD", "SELL"):
        return False
    orders = plan.get("orders")
    if not isinstance(orders, list):
        return False
    return True


def _normalize(plan: dict, signal: str, advice: dict | None) -> dict:
    """Clamp fields and ensure required keys."""
    plan = dict(plan)
    plan["rating"] = (plan.get("rating") or signal or "BUY").upper()
    plan["thesis"] = plan.get("thesis") or ""
    orders = []
    for o in plan.get("orders") or []:
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        trig = o.get("trigger") or {}
        if not t or not trig.get("kind"):
            continue
        pct = o.get("pct_target_total")
        try:
            pct = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct = None
        if pct is not None and pct > 1:
            pct = pct / 100.0
        orders.append({
            "type": t,
            "pct_target_total": pct if pct is not None else 0.0,
            "trigger": trig,
            "desc": o.get("desc") or o.get("description") or "",
        })
    plan["orders"] = orders
    return plan
