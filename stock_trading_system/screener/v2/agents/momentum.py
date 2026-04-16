"""MomentumAgent — measures multi-timeframe momentum strength."""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v2.momentum")


class MomentumAgent(BaseAgent):
    name = "momentum"
    data_source = "local_cache"

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        df = self._data.get_bars(ticker, period="1y", interval="1d")
        if df is None or df.empty or len(df) < 60:
            return self.make_score(0, "价格数据缺失或太短", {"error": "no_bars"})

        close = df["Close"]

        # Multi-timeframe returns
        r1m = self._data.pct_change(close, 21)
        r3m = self._data.pct_change(close, 63)
        r6m = self._data.pct_change(close, 126)
        r12m = self._data.pct_change(close, 252)

        # 52-week high proximity
        high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
        current = float(close.iloc[-1])
        dist_from_high = (high_52w - current) / high_52w if high_52w > 0 else 1.0

        # MA stack (10 > 50 > 200 = perfect uptrend)
        ma10 = float(close.tail(10).mean())
        ma50 = float(close.tail(50).mean()) if len(close) >= 50 else ma10
        ma200 = float(close.tail(200).mean()) if len(close) >= 200 else ma50
        ma_stacked = ma10 > ma50 > ma200

        # Scoring (0-100)
        score = 50.0
        signals = {
            "r1m": round(r1m * 100, 2) if r1m is not None else None,
            "r3m": round(r3m * 100, 2) if r3m is not None else None,
            "r6m": round(r6m * 100, 2) if r6m is not None else None,
            "r12m": round(r12m * 100, 2) if r12m is not None else None,
            "dist_from_52w_high_pct": round(dist_from_high * 100, 2),
            "ma_stacked": ma_stacked,
        }

        # Each return adds up to +10, caps
        for r, weight in [(r1m, 8), (r3m, 10), (r6m, 12), (r12m, 10)]:
            if r is None:
                continue
            # +30% over period → max weight, -30% → min
            contrib = max(-weight, min(weight, r / 0.3 * weight))
            score += contrib

        # MA stacking bonus
        if ma_stacked:
            score += 8
        elif ma10 < ma50 < ma200:
            score -= 10

        # Near 52W high bonus
        if dist_from_high < 0.05:
            score += 8
        elif dist_from_high < 0.10:
            score += 4
        elif dist_from_high > 0.40:
            score -= 6

        parts = []
        if r12m is not None:
            parts.append(f"12M {r12m*100:+.1f}%")
        if ma_stacked:
            parts.append("均线多头排列")
        if dist_from_high < 0.05:
            parts.append("接近 52W 新高")
        rationale = "，".join(parts) if parts else "动量信号中性"

        return self.make_score(score, rationale, signals)
