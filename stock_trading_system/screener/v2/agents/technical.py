"""TechnicalAgent — RSI, MACD, Bollinger, volume surge, pattern signals."""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class TechnicalAgent(BaseAgent):
    name = "technical"
    data_source = "local_cache"

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        df = self._data.get_bars(ticker, period="6mo", interval="1d")
        if df is None or df.empty or len(df) < 50:
            return self.make_score(0, "数据不足以计算技术指标", {"error": "no_bars"})

        close = df["Close"]
        volume = df["Volume"] if "Volume" in df else None

        rsi = self._data.rsi(close, 14) or 50.0

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd - macd_sig).iloc[-1])
        macd_cross_up = bool(macd.iloc[-2] <= macd_sig.iloc[-2] and macd.iloc[-1] > macd_sig.iloc[-1]) if len(macd) >= 2 else False

        # Bollinger Band position
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_up = bb_mid + 2 * bb_std
        bb_lo = bb_mid - 2 * bb_std
        bb_pos = None
        try:
            w = float(bb_up.iloc[-1] - bb_lo.iloc[-1])
            if w > 0:
                bb_pos = float((close.iloc[-1] - bb_lo.iloc[-1]) / w)
        except Exception:
            pass

        # Volume surge (today vs 20-day avg)
        vol_surge = None
        if volume is not None and len(volume) >= 20:
            avg20 = float(volume.tail(20).mean())
            today = float(volume.iloc[-1])
            if avg20 > 0:
                vol_surge = today / avg20

        signals = {
            "rsi": round(rsi, 1),
            "macd_histogram": round(macd_hist, 3),
            "macd_cross_up": macd_cross_up,
            "bb_position": round(bb_pos, 2) if bb_pos is not None else None,
            "volume_surge_ratio": round(vol_surge, 2) if vol_surge is not None else None,
        }

        # Scoring
        score = 50.0
        reasons = []

        # RSI: sweet spot 45-65, oversold 25-35 positive, >75 negative
        if 45 <= rsi <= 65:
            score += 8
            reasons.append(f"RSI {rsi:.1f} 健康")
        elif 25 <= rsi <= 35:
            score += 12
            reasons.append(f"RSI {rsi:.1f} 超卖")
        elif rsi > 75:
            score -= 10
            reasons.append(f"RSI {rsi:.1f} 超买")

        # MACD
        if macd_hist > 0:
            score += 6
        if macd_cross_up:
            score += 8
            reasons.append("MACD 金叉")

        # Bollinger
        if bb_pos is not None:
            if bb_pos < 0.2:
                score += 6
                reasons.append("布林下轨附近")
            elif bb_pos > 0.9:
                score -= 5

        # Volume surge
        if vol_surge is not None:
            if vol_surge > 2.5:
                score += 10
                reasons.append(f"放量 {vol_surge:.1f}x")
            elif vol_surge > 1.5:
                score += 4

        rationale = "，".join(reasons) if reasons else "技术信号中性"
        return self.make_score(score, rationale, signals)
