"""RegimeRelativeAgent — relative strength vs benchmark (SPY).

Scores how strongly the stock outperforms (or underperforms) SPY over
multiple timeframes. In bull regimes, high relative strength is rewarded.
"""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class RegimeRelativeAgent(BaseAgent):
    name = "regime_relative"
    data_source = "yfinance"

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper
        self._spy_cache = None

    def _get_spy_returns(self):
        """Cached SPY bar returns to avoid re-fetching per ticker."""
        if self._spy_cache is not None:
            return self._spy_cache
        df = self._data.get_bars("SPY", period="1y", interval="1d")
        if df is None or df.empty:
            self._spy_cache = None
            return None
        close = df["Close"]
        self._spy_cache = {
            "r1m": self._data.pct_change(close, 21),
            "r3m": self._data.pct_change(close, 63),
            "r6m": self._data.pct_change(close, 126),
            "r12m": self._data.pct_change(close, 252),
        }
        return self._spy_cache

    def score(self, ticker: str, context: dict) -> AgentScore:
        spy = self._get_spy_returns()
        if spy is None:
            return self.make_score(50, "SPY 数据不可用，中性", {"error": "no_spy"})

        df = self._data.get_bars(ticker, period="1y", interval="1d")
        if df is None or df.empty:
            return self.make_score(0, "个股数据不可用", {"error": "no_bars"})

        close = df["Close"]
        stock = {
            "r1m": self._data.pct_change(close, 21),
            "r3m": self._data.pct_change(close, 63),
            "r6m": self._data.pct_change(close, 126),
            "r12m": self._data.pct_change(close, 252),
        }

        # Relative strength: stock_return - spy_return
        rs = {}
        for k in ["r1m", "r3m", "r6m", "r12m"]:
            if stock[k] is not None and spy[k] is not None:
                rs[k] = stock[k] - spy[k]

        if not rs:
            return self.make_score(50, "收益数据不足", {})

        # RRG-style quadrant: RS-Ratio (long) + RS-Momentum (short delta)
        long_rs = rs.get("r6m") or rs.get("r3m") or 0.0
        short_rs = rs.get("r1m") or 0.0
        if long_rs > 0 and short_rs > 0:
            quadrant = "Leading"
        elif long_rs < 0 and short_rs > 0:
            quadrant = "Improving"
        elif long_rs < 0 and short_rs < 0:
            quadrant = "Lagging"
        else:
            quadrant = "Weakening"

        signals = {
            **{k: round(v * 100, 2) for k, v in rs.items()},
            "quadrant": quadrant,
        }

        score = 50.0
        reasons = []
        # Weight by timeframe
        for k, weight in [("r1m", 6), ("r3m", 10), ("r6m", 12), ("r12m", 10)]:
            if k not in rs:
                continue
            v = rs[k]
            # +20 pts outperformance → max weight
            contrib = max(-weight, min(weight, v / 0.2 * weight))
            score += contrib

        # Quadrant bonus
        if quadrant == "Leading":
            score += 8
            reasons.append("RRG Leading 象限")
        elif quadrant == "Improving":
            score += 4
            reasons.append("RRG Improving 象限")
        elif quadrant == "Lagging":
            score -= 6

        if rs.get("r6m") and rs["r6m"] > 0.1:
            reasons.append(f"6M 跑赢 SPY {rs['r6m']*100:+.1f}%")

        rationale = "，".join(reasons) if reasons else f"相对强度 {quadrant}"
        return self.make_score(score, rationale, signals)
