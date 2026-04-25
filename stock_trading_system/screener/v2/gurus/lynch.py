"""Peter Lynch — GARP (growth at a reasonable price)."""

from stock_trading_system.screener.v2.gurus.base import BaseGuru, GuruMatch


class LynchGuru(BaseGuru):
    name = "lynch"
    display_name = "Peter Lynch"
    philosophy = "GARP / 成长合理价"
    principles = ["PEG < 1", "利润增速 > 20%", "行业细分龙头", "现金流稳健"]
    motto = "买你了解的东西，做功课比听消息重要"
    avatar_initials = "PL"
    avatar_color = "#3882ff"

    def evaluate(self, ticker, fundamentals, context):
        met = []
        unmet = []

        if not fundamentals:
            return GuruMatch(match_pct=0, fit=False, reason="基本面数据缺失",
                             principles_met=[], principles_unmet=self.principles)

        peg = _f(fundamentals.get("peg"))
        rev_growth = _f(fundamentals.get("revenue_growth"))
        earn_growth = _f(fundamentals.get("earnings_growth"))
        mcap = _f(fundamentals.get("market_cap"))
        fcf = _f(fundamentals.get("free_cashflow"))

        # PEG < 1 (but > 0)
        if peg is not None and 0 < peg < 1.0:
            met.append("PEG < 1")
        else:
            unmet.append("PEG < 1")

        # Earnings or revenue growth > 20%
        growth = earn_growth if earn_growth is not None else rev_growth
        if growth is not None and growth > 0.20:
            met.append("利润增速 > 20%")
        else:
            unmet.append("利润增速 > 20%")

        # Niche leader proxy: mid-cap (5B-50B) + high margin
        if mcap is not None:
            if 5e9 < mcap < 50e9:
                met.append("行业细分龙头")
            else:
                unmet.append("行业细分龙头")
        else:
            unmet.append("行业细分龙头")

        # Cash flow healthy
        if fcf is not None and fcf > 0:
            met.append("现金流稳健")
        else:
            unmet.append("现金流稳健")

        parts = []
        if peg is not None: parts.append(f"PEG {peg:.2f}")
        if growth is not None: parts.append(f"增速 {growth*100:+.0f}%")
        reason = " · ".join(parts) if parts else f"符合 {len(met)}/4 条 Lynch 原则"
        return self.make_match(met, unmet, reason)


def _f(v):
    try:
        if v is None: return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None
