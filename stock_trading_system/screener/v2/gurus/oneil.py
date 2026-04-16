"""William O'Neil — CANSLIM momentum growth."""

from stock_trading_system.screener.v2.gurus.base import BaseGuru, GuruMatch


class ONeilGuru(BaseGuru):
    name = "oneil"
    display_name = "William O'Neil"
    philosophy = "CANSLIM / 动量成长"
    principles = ["C: EPS 加速", "A: 年化盈利 +25%", "N: 突破新高", "S: 供需（放量）",
                  "L: 行业龙头（相对强度 80+）", "I: 机构增持", "M: 市场向好"]
    motto = "最赚钱的股票往往是你觉得已经太贵的那只"
    avatar_initials = "WO"
    avatar_color = "#00ff88"

    def evaluate(self, ticker, fundamentals, context):
        """Uses both fundamentals and price context (passed in context['bars_summary'])."""
        met = []
        unmet = []

        summary = ((context or {}).get("canslim_signals", {}) or {}).get(ticker, {})

        # C: EPS 加速（用 earnings_growth 近似）
        earn_growth = _f((fundamentals or {}).get("earnings_growth"))
        if earn_growth is not None and earn_growth > 0.25:
            met.append("C: EPS 加速")
        else:
            unmet.append("C: EPS 加速")

        # A: Annual earnings 年增长 +25%
        if earn_growth is not None and earn_growth > 0.25:
            met.append("A: 年化盈利 +25%")
        else:
            unmet.append("A: 年化盈利 +25%")

        # N: 突破新高 (from price context — dist_from_52w_high < 5%)
        near_high = summary.get("near_52w_high", False)
        if near_high:
            met.append("N: 突破新高")
        else:
            unmet.append("N: 突破新高")

        # S: 放量（volume_surge > 1.5）
        if summary.get("volume_surge", 0) > 1.5:
            met.append("S: 供需（放量）")
        else:
            unmet.append("S: 供需（放量）")

        # L: 相对强度（RS > 80 意味着好于 80% 个股 — 我们用 regime_relative 替代）
        if summary.get("rs_leading", False):
            met.append("L: 行业龙头")
        else:
            unmet.append("L: 行业龙头")

        # I: 机构持股（yfinance 不提供，先跳过但标为未验证）
        unmet.append("I: 机构增持")

        # M: 市场向好（来自 regime）
        regime = (context or {}).get("regime_label", "sideways")
        if regime == "bull":
            met.append("M: 市场向好")
        else:
            unmet.append("M: 市场向好")

        reason = f"CANSLIM 符合 {len(met)}/7 条"
        return self.make_match(met, unmet, reason)


def _f(v):
    try:
        if v is None: return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None
