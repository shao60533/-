"""Warren Buffett — value investing, economic moat."""

from stock_trading_system.screener.v2.gurus.base import BaseGuru, GuruMatch


class BuffettGuru(BaseGuru):
    name = "buffett"
    display_name = "Warren Buffett"
    philosophy = "价值投资 / 护城河"
    principles = ["经济护城河", "ROE > 15%", "低负债", "长期自由现金流"]
    motto = "在别人贪婪时恐惧，在别人恐惧时贪婪"
    avatar_initials = "WB"
    avatar_color = "#c0a882"

    def evaluate(self, ticker, fundamentals, context):
        met = []
        unmet = []
        reasons = []

        if not fundamentals:
            return GuruMatch(match_pct=0, fit=False, reason="基本面数据缺失",
                             principles_met=[], principles_unmet=self.principles)

        roe = _f(fundamentals.get("roe"))
        d2e = _f(fundamentals.get("debt_to_equity"))
        d2e_adj = (d2e / 100) if (d2e and d2e > 10) else d2e
        fcf = _f(fundamentals.get("free_cashflow"))
        mcap = _f(fundamentals.get("market_cap"))
        margin = _f(fundamentals.get("profit_margin"))
        op_margin = _f(fundamentals.get("operating_margin"))

        # ROE > 15%
        if roe is not None:
            if roe > 0.15:
                met.append("ROE > 15%")
                reasons.append(f"ROE {roe*100:.1f}%")
            else:
                unmet.append("ROE > 15%")
        else:
            unmet.append("ROE > 15%")

        # Low debt (D/E < 0.5)
        if d2e_adj is not None:
            if d2e_adj < 0.5:
                met.append("低负债")
            else:
                unmet.append("低负债")
        else:
            unmet.append("低负债")

        # Long-term FCF (positive + meaningful yield)
        if fcf and mcap and fcf > 0:
            fcf_yield = fcf / mcap
            if fcf_yield > 0.03:
                met.append("长期自由现金流")
                reasons.append(f"FCF 收益率 {fcf_yield*100:.1f}%")
            else:
                unmet.append("长期自由现金流")
        else:
            unmet.append("长期自由现金流")

        # Moat proxy: high & durable margins
        if margin is not None and op_margin is not None:
            if margin > 0.15 and op_margin > 0.20:
                met.append("经济护城河")
                reasons.append("高利润率护城河")
            else:
                unmet.append("经济护城河")
        else:
            unmet.append("经济护城河")

        reason = "，".join(reasons) if reasons else f"符合 {len(met)}/4 条 Buffett 原则"
        return self.make_match(met, unmet, reason)


def _f(v):
    try:
        if v is None: return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None
