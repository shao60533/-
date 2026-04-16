"""Benjamin Graham — deep value, margin of safety."""

from stock_trading_system.screener.v2.gurus.base import BaseGuru, GuruMatch


class GrahamGuru(BaseGuru):
    name = "graham"
    display_name = "Benjamin Graham"
    philosophy = "深度价值 / 安全边际"
    principles = ["P/B < 1.5", "P/E < 15", "流动比率 > 2", "净资产折价"]
    motto = "市场短期是投票机，长期是称重机"
    avatar_initials = "BG"
    avatar_color = "#6b7a99"

    def evaluate(self, ticker, fundamentals, context):
        met = []
        unmet = []

        if not fundamentals:
            return GuruMatch(match_pct=0, fit=False, reason="基本面数据缺失",
                             principles_met=[], principles_unmet=self.principles)

        pe = _f(fundamentals.get("pe"))
        pb = _f(fundamentals.get("pb"))
        current_ratio = _f(fundamentals.get("current_ratio"))

        if pb is not None and 0 < pb < 1.5:
            met.append("P/B < 1.5")
        else:
            unmet.append("P/B < 1.5")

        if pe is not None and 0 < pe < 15:
            met.append("P/E < 15")
        else:
            unmet.append("P/E < 15")

        if current_ratio is not None and current_ratio > 2.0:
            met.append("流动比率 > 2")
        else:
            unmet.append("流动比率 > 2")

        # Net asset discount proxy: P/B < 1.2
        if pb is not None and 0 < pb < 1.2:
            met.append("净资产折价")
        else:
            unmet.append("净资产折价")

        parts = []
        if pe is not None: parts.append(f"P/E {pe:.1f}")
        if pb is not None: parts.append(f"P/B {pb:.2f}")
        reason = " · ".join(parts) if parts else f"符合 {len(met)}/4 条 Graham 原则"
        return self.make_match(met, unmet, reason)


def _f(v):
    try:
        if v is None: return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None
