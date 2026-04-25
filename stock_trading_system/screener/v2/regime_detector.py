"""Market regime detector — bull / bear / sideways.

Inputs (via yfinance, cached):
  - SPY price history (for 200MA check + breadth proxy)
  - ^VIX level

Output:
  RegimeResult(label, confidence, weights, stats)

Weights are regime-adaptive: different agent importance per regime.
Falls back gracefully to "sideways" if data unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from stock_trading_system.utils import get_logger

logger = get_logger("screener.v2.regime")


# Default agent weights per regime (must sum to ~1.0; normalized later).
_DEFAULT_WEIGHTS = {
    "bull": {
        "momentum": 0.20, "quality_value": 0.10, "catalyst": 0.12,
        "sentiment": 0.10, "technical": 0.12, "regime_relative": 0.15,
        "guru": 0.10, "risk": 0.11,
    },
    "bear": {
        "momentum": 0.08, "quality_value": 0.22, "catalyst": 0.10,
        "sentiment": 0.08, "technical": 0.10, "regime_relative": 0.10,
        "guru": 0.20, "risk": 0.12,
    },
    "sideways": {
        "momentum": 0.12, "quality_value": 0.15, "catalyst": 0.15,
        "sentiment": 0.10, "technical": 0.15, "regime_relative": 0.10,
        "guru": 0.12, "risk": 0.11,
    },
}


@dataclass
class RegimeResult:
    label: str                       # "bull" | "bear" | "sideways"
    confidence: float                # 0-1
    weights: dict                    # {agent_name: weight}
    stats: dict = field(default_factory=dict)   # raw stats for UI

    def to_dict(self) -> dict:
        return asdict(self)


class RegimeDetector:
    """Detect current US market regime using SPY + VIX.

    Cached via LocalCache (30 min TTL) to avoid repeated yfinance calls.
    """

    def __init__(self, config: dict, local_cache=None):
        self._config = config
        self._cache = local_cache
        cfg = (config.get("screener", {}) or {}).get("v2", {}).get("regime_detection", {}) or {}
        self._ma_period = int(cfg.get("spy_ma_period", 200))
        self._vix_bull = float(cfg.get("vix_bull_threshold", 20))
        self._vix_bear = float(cfg.get("vix_bear_threshold", 30))
        self._weights_cfg = {
            "bull": (config.get("screener", {}) or {}).get("v2", {}).get("weights", {}).get("bull") or _DEFAULT_WEIGHTS["bull"],
            "bear": (config.get("screener", {}) or {}).get("v2", {}).get("weights", {}).get("bear") or _DEFAULT_WEIGHTS["bear"],
            "sideways": (config.get("screener", {}) or {}).get("v2", {}).get("weights", {}).get("sideways") or _DEFAULT_WEIGHTS["sideways"],
        }

    def detect(self) -> RegimeResult:
        """Return current regime. Falls back to sideways on data failure."""
        # Cache lookup
        if self._cache is not None:
            cached = self._cache.get("regime", "us_current")
            if cached is not None:
                return RegimeResult(**cached)

        try:
            import yfinance as yf
            spy = yf.Ticker("SPY").history(period="1y", auto_adjust=True)
            vix = yf.Ticker("^VIX").history(period="1mo", auto_adjust=True)
            if spy is None or spy.empty or vix is None or vix.empty:
                raise ValueError("empty history")

            close = spy["Close"]
            current = float(close.iloc[-1])
            ma = float(close.tail(self._ma_period).mean())
            vix_last = float(vix["Close"].iloc[-1])

            # Breadth proxy: fraction of last 60 sessions closed above 50MA
            last60 = close.tail(60)
            ma50 = close.rolling(50).mean().tail(60)
            breadth = float((last60 > ma50).mean()) if not ma50.empty else 0.5

            result = self._classify(current, ma, vix_last, breadth)
        except Exception as e:  # noqa: BLE001
            logger.warning("Regime detection failed, falling back to sideways: %s", e)
            result = RegimeResult(
                label="sideways",
                confidence=0.5,
                weights=self._weights_cfg["sideways"],
                stats={"error": str(e)},
            )

        # Cache (30 min default, set via cache TTL config)
        if self._cache is not None:
            self._cache.set("regime", "us_current", result.to_dict())
        return result

    def _classify(
        self, current: float, ma200: float, vix: float, breadth: float
    ) -> RegimeResult:
        above_ma = current > ma200
        ma_dist_pct = (current - ma200) / ma200 if ma200 > 0 else 0.0

        if above_ma and vix < self._vix_bull and breadth > 0.55:
            conf = min(0.95, 0.6 + min(0.2, ma_dist_pct) + (0.55 - vix / 100))
            label = "bull"
        elif (not above_ma) or vix > self._vix_bear:
            conf = min(0.95, 0.6 + max(0.0, (vix - 20) / 50))
            label = "bear"
        else:
            conf = 0.65
            label = "sideways"

        return RegimeResult(
            label=label,
            confidence=round(conf, 2),
            weights=self._weights_cfg[label],
            stats={
                "spy_current": round(current, 2),
                "spy_ma200": round(ma200, 2),
                "ma_dist_pct": round(ma_dist_pct * 100, 2),
                "vix": round(vix, 2),
                "breadth_pct": round(breadth * 100, 1),
            },
        )
