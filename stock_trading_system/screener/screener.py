"""Layer 3: AI-powered stock screener - orchestrates 3-layer screening — DEPRECATED.

hardening-iteration-v1 P3.1 [H12] — this is the legacy v1 screener.
Replaced by ``stock_trading_system.screener.v3.pipeline.ScreenerV3Pipeline``
(14 guru agents, roundtable consensus, integrated cache, async). Three
call sites still bind to this module:

    web/app.py:72          (used to be ``/api/screen``)
    alerts/telegram_bot.py (``/screen`` Telegram command)
    main.py CLI            (``stock screen``)

A v3 ``screen_sync(market, strategy)`` wrapper that mirrors the v1 dict
shape is the migration target; once that's in place, the three sites
flip and this module deletes. Until then the DeprecationWarning below
makes the legacy path visible to anyone re-importing.

Original notes — kept for diff context:

US: IB Scanner -> finviz fundamentals -> Gemini AI evaluation
CN: AkShare screening -> Gemini AI evaluation
"""

import warnings

from stock_trading_system.screener.criteria import ScreenCriteria, STRATEGIES
from stock_trading_system.screener.ib_scanner import IBScanner
from stock_trading_system.screener.finviz_screener import FinvizScreener
from stock_trading_system.screener.akshare_screener import AkShareScreener
from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.agents.analyzer import StockAnalyzer
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import today_str

logger = get_logger("screener")

warnings.warn(
    "stock_trading_system.screener.screener (v1 StockScreener) is "
    "deprecated — use stock_trading_system.screener.v3 pipeline. "
    "Scheduled for deletion after the v3 sync-wrapper PR retires "
    "the three remaining call sites (web/app.py, telegram_bot.py, "
    "main.py CLI). See hardening-iteration-v1 P3.1 / H12.",
    DeprecationWarning,
    stacklevel=2,
)


class StockScreener:
    """3-layer stock screener with AI-powered final selection."""

    def __init__(self, config: dict):
        self._config = config
        self._data_manager = DataManager(config)
        self._analyzer = StockAnalyzer(config)

    def screen(
        self,
        market: str = "us",
        strategy: str = "growth",
        criteria: ScreenCriteria | None = None,
    ) -> list[dict]:
        """Run full screening pipeline.

        Args:
            market: "us", "cn", or "all"
            strategy: "growth", "value", "momentum", "low_volatility"
            criteria: Custom criteria (uses strategy template if None)

        Returns:
            Sorted list of recommended stocks with analysis
        """
        criteria = criteria or STRATEGIES.get(strategy, STRATEGIES["growth"])
        results = []

        if market in ("us", "all"):
            results.extend(self._screen_us(strategy, criteria))

        if market in ("cn", "all"):
            results.extend(self._screen_cn(strategy, criteria))

        return results

    def _screen_us(self, strategy: str, criteria: ScreenCriteria) -> list[dict]:
        """US market 3-layer screening: IB Scanner -> finviz -> AI."""
        logger.info("Starting US screening with strategy: %s", strategy)

        # Layer 1: IB Scanner coarse screening
        candidates = []
        ib = self._data_manager.get_ib_provider()
        if self._config.get("ib", {}).get("enabled"):
            try:
                scanner = IBScanner(ib)
                candidates = scanner.scan(strategy=strategy, criteria=criteria)
                logger.info("Layer 1 (IB Scanner): %d candidates", len(candidates))
            except Exception as e:
                logger.warning("IB Scanner unavailable: %s. Skipping Layer 1.", e)

        if not candidates:
            logger.info("IB Scanner unavailable, using finviz-only screening")
            # Fallback: screen popular stocks via finviz
            candidates = _get_default_us_tickers()

        # Layer 2: Finviz fundamental filtering
        finviz = FinvizScreener()
        filtered = finviz.filter(candidates, criteria)
        logger.info("Layer 2 (finviz): %d passed fundamental filters", len(filtered))

        if not filtered:
            # Finviz unavailable (e.g. network blocked): fall back to Qwen AI
            # screening over the raw candidate list if it is configured.
            qwen = self._data_manager.get_qwen_provider()
            if qwen.enabled and candidates:
                logger.info("Layer 2 skipped, trying Qwen AI screening over raw candidates")
                tickers = [c if isinstance(c, str) else c.get("ticker", "") for c in candidates]
                tickers = [t for t in tickers if t]
                return self._qwen_evaluate(tickers, strategy, criteria.top_n)
            return []

        # Layer 3: AI evaluation (Gemini first, Qwen as backup)
        return self._ai_evaluate(filtered, criteria.top_n, strategy=strategy)

    def _screen_cn(self, strategy: str, criteria: ScreenCriteria) -> list[dict]:
        """A-share screening: AkShare -> AI."""
        logger.info("Starting A-share screening with strategy: %s", strategy)

        # Adjust criteria for A-share market
        cn_config = self._config.get("screener", {}).get("cn_market", {})
        cn_criteria = ScreenCriteria(
            min_market_cap=cn_config.get("min_market_cap", criteria.min_market_cap),
            min_volume=cn_config.get("min_volume", criteria.min_volume),
            max_pe=cn_config.get("max_pe", criteria.max_pe),
            top_n=cn_config.get("top_n", criteria.top_n),
        )

        # Layer 1: AkShare screening
        ak_screener = AkShareScreener()
        candidates = ak_screener.screen(cn_criteria)
        logger.info("Layer 1 (AkShare): %d candidates", len(candidates))

        if not candidates:
            return []

        # Layer 2: AI evaluation
        return self._ai_evaluate(candidates, cn_criteria.top_n, strategy=strategy)

    def _ai_evaluate(
        self,
        candidates: list[dict],
        top_n: int,
        strategy: str = "growth",
    ) -> list[dict]:
        """AI-evaluate candidates: Gemini (TradingAgents) first, Qwen as fallback.

        Note: TradingAgents primarily supports US stocks via yfinance.
        If the Gemini-backed analyzer is not configured, fall through to Qwen
        batch ranking which uses a single LLM call over the full candidate list.
        """
        date = today_str()
        evaluated = []
        gemini_ok_count = 0

        for stock in candidates[:top_n * 2]:  # Evaluate up to 2x top_n
            ticker = stock.get("ticker", "")
            try:
                signal = self._analyzer.quick_screen(ticker, date)
                stock["signal"] = signal
                stock["summary"] = f"AI Signal: {signal}"
                gemini_ok_count += 1
                logger.info("AI evaluated %s: %s", ticker, signal)
            except Exception as e:
                logger.warning("Gemini evaluation failed for %s: %s", ticker, e)
                stock["signal"] = "N/A"
                stock["summary"] = "AI evaluation unavailable"
            evaluated.append(stock)

        # If Gemini produced nothing usable, try Qwen as a batch fallback
        if gemini_ok_count == 0:
            qwen = self._data_manager.get_qwen_provider()
            if qwen.enabled:
                logger.info("Gemini evaluation unavailable, trying Qwen batch screening")
                tickers = [s.get("ticker", "") for s in evaluated if s.get("ticker")]
                qwen_picks = self._qwen_evaluate(tickers, strategy, top_n)
                if qwen_picks:
                    # Merge Qwen signals back onto the finviz metadata
                    by_ticker = {s.get("ticker"): s for s in evaluated}
                    merged = []
                    for p in qwen_picks:
                        base = dict(by_ticker.get(p["ticker"], {}))
                        base.update({
                            "ticker": p["ticker"],
                            "name": p.get("name") or base.get("name", ""),
                            "signal": p["signal"],
                            "summary": p.get("summary") or f"Qwen Signal: {p['signal']}",
                            "score": p.get("score", 0),
                        })
                        merged.append(base)
                    return merged

        # Sort: BUY first, then HOLD, then SELL
        signal_order = {"BUY": 0, "HOLD": 1, "SELL": 2, "N/A": 3}
        evaluated.sort(key=lambda x: signal_order.get(x.get("signal", "N/A"), 3))

        return evaluated[:top_n]

    def _qwen_evaluate(
        self,
        tickers: list[str],
        strategy: str,
        top_n: int,
    ) -> list[dict]:
        """Use Qwen to rank tickers in a single batch call."""
        qwen = self._data_manager.get_qwen_provider()
        if not qwen.enabled or not tickers:
            return []
        try:
            return qwen.screen_stocks(tickers, strategy=strategy, top_n=top_n)
        except Exception as e:
            logger.warning("Qwen screening failed: %s", e)
            return []


def _get_default_us_tickers() -> list[str]:
    """Default US stock universe when IB Scanner is unavailable."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
        "UNH", "JNJ", "JPM", "V", "PG", "MA", "HD", "AVGO", "MRK", "ABBV",
        "PEP", "KO", "COST", "TMO", "ADBE", "CRM", "ACN", "MCD", "CSCO",
        "NKE", "TXN", "AMD", "INTC", "QCOM", "AMAT", "LRCX", "KLAC",
        "NFLX", "DIS", "PYPL", "SQ", "SNAP", "UBER", "LYFT", "ABNB",
        "COIN", "PLTR", "SOFI", "RIVN", "LCID", "NIO",
    ]
