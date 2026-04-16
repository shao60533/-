"""RiskAgent — Beta, drawdown, ATR, liquidity, short squeeze warning."""

from stock_trading_system.screener.v2.agents.base import BaseAgent, AgentScore


class RiskAgent(BaseAgent):
    name = "risk"
    data_source = "local_cache"

    def __init__(self, config: dict, data_helper):
        super().__init__(config)
        self._data = data_helper

    def score(self, ticker: str, context: dict) -> AgentScore:
        df = self._data.get_bars(ticker, period="1y", interval="1d")
        f = self._data.get_fundamentals(ticker) or {}

        if df is None or df.empty:
            return self.make_score(50, "数据不足，风险中性", {"error": "no_bars"})

        close = df["Close"]

        # Max drawdown (1y)
        running_max = close.expanding().max()
        drawdown = (close - running_max) / running_max
        max_dd = float(drawdown.min())   # negative

        # ATR (14)
        try:
            high = df["High"]; low = df["Low"]; prev_close = close.shift(1)
            tr = (high - low).combine((high - prev_close).abs(), max).combine((low - prev_close).abs(), max)
            atr = float(tr.rolling(14).mean().iloc[-1])
            atr_pct = atr / float(close.iloc[-1]) if float(close.iloc[-1]) > 0 else None
        except Exception:
            atr_pct = None

        beta = _safe(f.get("beta"))
        short_ratio = _safe(f.get("short_ratio"))
        short_pct = _safe(f.get("short_percent_of_float"))

        # Liquidity (avg 20d dollar volume)
        try:
            vol20 = df["Volume"].tail(20).mean() if "Volume" in df else None
            px = float(close.iloc[-1])
            dollar_vol = float(vol20 * px) if vol20 is not None else None
        except Exception:
            dollar_vol = None

        # Squeeze risk: short_pct > 15% AND short_ratio > 5
        squeeze_risk = bool(short_pct and short_pct > 0.15 and short_ratio and short_ratio > 5)

        signals = {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "atr_pct": round(atr_pct * 100, 2) if atr_pct is not None else None,
            "beta": round(beta, 2) if beta is not None else None,
            "short_percent_float": round(short_pct * 100, 2) if short_pct is not None else None,
            "short_ratio": round(short_ratio, 2) if short_ratio is not None else None,
            "dollar_volume_20d": round(dollar_vol, 0) if dollar_vol is not None else None,
            "squeeze_risk": squeeze_risk,
        }

        # Higher score = lower risk
        score = 70.0
        reasons = []

        # Drawdown
        if max_dd < -0.40: score -= 20; reasons.append(f"最大回撤 {max_dd*100:.0f}% 较大")
        elif max_dd < -0.25: score -= 8
        elif max_dd > -0.10: score += 5

        # Beta
        if beta is not None:
            if beta > 2: score -= 12; reasons.append(f"Beta {beta:.2f} 高")
            elif beta > 1.5: score -= 5
            elif beta < 0.8: score += 8; reasons.append(f"低 Beta {beta:.2f}")

        # ATR
        if atr_pct is not None:
            if atr_pct > 0.05: score -= 8
            elif atr_pct < 0.02: score += 5

        # Liquidity
        if dollar_vol is not None and dollar_vol < 5_000_000:
            score -= 15; reasons.append("流动性偏低")

        # Squeeze
        if squeeze_risk:
            score -= 5; reasons.append("做空挤压风险")

        if not reasons:
            reasons.append("风险适中")
        return self.make_score(score, "，".join(reasons), signals)


def _safe(v):
    try:
        if v is None:
            return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None
