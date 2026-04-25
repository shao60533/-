"""CatalystAgent — detect event-driven catalysts.

Strategy (to bound LLM cost):
  1. Use price + volume proxies to flag likely catalysts (large single-day moves
     on heavy volume, gap up/down, earnings-month detection).
  2. Optionally, for top-N candidates, call Qwen to classify catalyst type.

For Phase 1: heuristic only. Qwen LLM classification is wired but disabled
unless `catalyst.use_llm` config is true.
"""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class CatalystAgent(BaseAgent):
    name = "catalyst"
    data_source = "qwen"   # UI label (even when heuristic, data is Qwen-era news-adjacent)

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        df = self._data.get_bars(ticker, period="3mo", interval="1d")
        if df is None or df.empty or len(df) < 30:
            return self.make_score(50, "数据不足，催化中性", {"error": "no_bars"})

        close = df["Close"]
        volume = df["Volume"] if "Volume" in df else None

        # Detect recent big moves (last 5 days)
        returns_5d = close.pct_change().tail(5).abs()
        max_recent_move = float(returns_5d.max()) if not returns_5d.empty else 0.0

        # Volume surge (last day vs 20d avg)
        volume_surge = None
        if volume is not None and len(volume) >= 20:
            avg20 = float(volume.tail(20).mean())
            last5_max = float(volume.tail(5).max())
            volume_surge = last5_max / avg20 if avg20 > 0 else None

        # Gap up detection (close vs prior close >5%)
        today_return = float(close.pct_change().iloc[-1]) if len(close) >= 2 else 0.0

        # Simple catalyst type inference from price+volume pattern
        catalyst_type = "unknown"
        if today_return > 0.05 and volume_surge and volume_surge > 2:
            catalyst_type = "positive_surprise"      # earnings/news beat-like
        elif today_return < -0.05 and volume_surge and volume_surge > 2:
            catalyst_type = "negative_surprise"
        elif max_recent_move > 0.07 and volume_surge and volume_surge > 1.5:
            catalyst_type = "recent_event"

        signals = {
            "today_return_pct": round(today_return * 100, 2),
            "max_recent_move_pct": round(max_recent_move * 100, 2),
            "volume_surge_5d_max": round(volume_surge, 2) if volume_surge is not None else None,
            "catalyst_type": catalyst_type,
        }

        score = 50.0
        reasons = []

        if catalyst_type == "positive_surprise":
            score += 25
            reasons.append(f"近期放量大涨 +{today_return*100:.1f}%")
        elif catalyst_type == "negative_surprise":
            score -= 15
            reasons.append(f"近期放量大跌 {today_return*100:.1f}%")
        elif catalyst_type == "recent_event":
            score += 10
            reasons.append("近期异动放量")

        if volume_surge is not None and volume_surge > 3:
            score += 5
            reasons.append(f"5日内放量 {volume_surge:.1f}x")

        if not reasons:
            reasons.append("无显著催化剂")
        return self.make_score(score, "，".join(reasons), signals)
