"""QualityValueAgent — ROE, margins, FCF yield, PEG, debt/equity."""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class QualityValueAgent(BaseAgent):
    name = "quality_value"
    data_source = "qwen"   # labeled as qwen (fallback to yfinance via DataHelper)

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        f = self._data.get_fundamentals(ticker)
        if not f:
            return self.make_score(0, "基本面数据不可用", {"error": "no_fundamentals"})

        roe = _safe(f.get("roe"))                   # 0.20 = 20%
        margin = _safe(f.get("profit_margin"))
        op_margin = _safe(f.get("operating_margin"))
        fcf = _safe(f.get("free_cashflow"))
        mcap = _safe(f.get("market_cap"))
        fcf_yield = (fcf / mcap) if (fcf and mcap) else None
        peg = _safe(f.get("peg"))
        d2e = _safe(f.get("debt_to_equity"))
        pe = _safe(f.get("pe"))

        signals = {
            "roe": _round_pct(roe),
            "profit_margin": _round_pct(margin),
            "operating_margin": _round_pct(op_margin),
            "fcf_yield": _round_pct(fcf_yield),
            "peg": round(peg, 2) if peg is not None else None,
            "debt_to_equity": round(d2e, 2) if d2e is not None else None,
            "pe": round(pe, 2) if pe is not None else None,
        }

        score = 50.0
        reasons = []

        # ROE: >20% A, 15-20% B, 10-15% C, <10% weak
        if roe is not None:
            if roe > 0.20: score += 12; reasons.append(f"ROE {roe*100:.1f}% 优秀")
            elif roe > 0.15: score += 7
            elif roe > 0.10: score += 2
            elif roe < 0.05: score -= 10

        # Margins
        if margin is not None:
            if margin > 0.20: score += 8
            elif margin > 0.10: score += 3
            elif margin < 0: score -= 12

        if op_margin is not None and op_margin > 0.15:
            score += 4

        # FCF yield (>5% attractive)
        if fcf_yield is not None:
            if fcf_yield > 0.05: score += 10; reasons.append(f"FCF 收益率 {fcf_yield*100:.1f}%")
            elif fcf_yield > 0.03: score += 5
            elif fcf_yield < 0: score -= 8

        # PEG < 1 = undervalued growth
        if peg is not None and peg > 0:
            if peg < 1.0: score += 8; reasons.append(f"PEG {peg:.2f} 合理")
            elif peg < 1.5: score += 3
            elif peg > 3: score -= 8

        # Debt/Equity: <0.5 healthy, >2 worrying
        if d2e is not None:
            d2e_adj = d2e / 100 if d2e > 10 else d2e   # yfinance sometimes returns pct
            if d2e_adj < 0.5: score += 5
            elif d2e_adj > 2: score -= 8

        # Negative earnings penalty
        if pe is not None and pe < 0:
            score -= 10

        if not reasons:
            reasons.append("基本面中等")
        rationale = "，".join(reasons)
        return self.make_score(score, rationale, signals)


def _safe(v):
    try:
        if v is None:
            return None
        x = float(v)
        return x if x == x else None   # filter NaN
    except Exception:
        return None


def _round_pct(v):
    return round(v * 100, 2) if v is not None else None
