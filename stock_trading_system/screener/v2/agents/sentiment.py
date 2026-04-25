"""SentimentAgent — sentiment proxy via price action + optional Qwen.

Phase 1: uses price-based sentiment proxies (trend persistence, volatility smile).
Phase 2 (future): optional Qwen web search for analyst revisions + social.
"""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class SentimentAgent(BaseAgent):
    name = "sentiment"
    data_source = "qwen"

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        df = self._data.get_bars(ticker, period="3mo", interval="1d")
        if df is None or df.empty or len(df) < 20:
            return self.make_score(50, "数据不足，情绪中性", {"error": "no_bars"})

        close = df["Close"]

        # Trend persistence (fraction of up days in last 30)
        returns = close.pct_change().dropna().tail(30)
        up_days = (returns > 0).sum()
        up_ratio = float(up_days / len(returns)) if len(returns) > 0 else 0.5

        # Recent trend direction (20-day slope relative)
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        slope_up = bool(ma5 > ma20)

        # Volatility trend (rising vol = fear, falling vol = complacency)
        vol_recent = float(returns.tail(10).std())
        vol_prior = float(returns.iloc[:20].std()) if len(returns) >= 30 else vol_recent
        vol_rising = vol_recent > vol_prior * 1.2

        signals = {
            "up_day_ratio_30d": round(up_ratio, 2),
            "ma5_above_ma20": slope_up,
            "vol_rising": vol_rising,
        }

        score = 50.0
        reasons = []

        if up_ratio > 0.6:
            score += 15
            reasons.append(f"近 30 日 {int(up_ratio*100)}% 上涨日")
        elif up_ratio > 0.55:
            score += 8
        elif up_ratio < 0.35:
            score -= 12
            reasons.append("近期下跌日占多")

        if slope_up:
            score += 8
        else:
            score -= 4

        if vol_rising:
            score -= 8
            reasons.append("波动率上升（避险）")
        else:
            score += 3

        if not reasons:
            reasons.append("情绪中性")
        return self.make_score(score, "，".join(reasons), signals)
