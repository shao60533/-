"""Stock analyzer - wraps TradingAgents library for multi-agent AI analysis.

Uses TradingAgents' built-in agents:
- Market Analyst (technical)
- Sentiment Analyst
- News Analyst
- Fundamentals Analyst
- Bull/Bear Debate + Judge
- Risk Manager
- Trader (final decision)

Data is fetched automatically by TradingAgents (yfinance + Alpha Vantage).
"""

import os
from dataclasses import dataclass, field

from stock_trading_system.utils import get_logger

logger = get_logger("agents.analyzer")


@dataclass
class AnalysisResult:
    """Structured result from multi-agent analysis."""
    ticker: str
    signal: str  # "BUY", "SELL", "HOLD"
    market_report: str = ""
    sentiment_report: str = ""
    news_report: str = ""
    fundamentals_report: str = ""
    investment_debate: dict = field(default_factory=dict)
    risk_assessment: dict = field(default_factory=dict)
    trade_decision: dict = field(default_factory=dict)


class StockAnalyzer:
    """Wraps TradingAgents for multi-agent stock analysis using Gemini."""

    def __init__(self, config: dict):
        self._config = config
        self._graph = None

    def _init_graph(self):
        """Lazy-init TradingAgents graph."""
        if self._graph is not None:
            return

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        gemini_config = self._config.get("gemini", {})

        # Set API key in environment
        api_key = gemini_config.get("api_key", "")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key

        ta_config = DEFAULT_CONFIG.copy()
        ta_config["llm_provider"] = "google"
        ta_config["deep_think_llm"] = gemini_config.get("deep_think_model", "gemini-2.0-pro")
        ta_config["quick_think_llm"] = gemini_config.get("model", "gemini-2.0-flash")
        ta_config["google_thinking_level"] = gemini_config.get("thinking_level", "high")
        ta_config["output_language"] = "Chinese"

        self._graph = TradingAgentsGraph(
            selected_analysts=["market", "sentiment", "news", "fundamentals"],
            debug=True,
            config=ta_config,
        )
        logger.info("TradingAgents graph initialized with Gemini")

    def analyze(self, ticker: str, date: str) -> AnalysisResult:
        """Run full multi-agent analysis on a stock.

        Args:
            ticker: Stock symbol (e.g. "AAPL")
            date: Analysis date "YYYY-MM-DD"

        Returns:
            AnalysisResult with signal, reports, and decision details
        """
        self._init_graph()

        logger.info("Starting analysis for %s on %s", ticker, date)
        final_state, signal = self._graph.propagate(ticker, date)

        result = AnalysisResult(
            ticker=ticker,
            signal=str(signal),
            market_report=final_state.get("market_report", ""),
            sentiment_report=final_state.get("sentiment_report", ""),
            news_report=final_state.get("news_report", ""),
            fundamentals_report=final_state.get("fundamentals_report", ""),
            investment_debate=final_state.get("investment_debate_state", {}),
            risk_assessment=final_state.get("risk_debate_state", {}),
            trade_decision=final_state.get("final_trade_decision", {}),
        )

        logger.info("Analysis complete for %s: signal=%s", ticker, signal)
        return result

    def quick_screen(self, ticker: str, date: str) -> str:
        """Quick analysis returning just the signal (for batch screening).

        Returns: "BUY", "SELL", or "HOLD"
        """
        self._init_graph()

        try:
            _, signal = self._graph.propagate(ticker, date)
            return str(signal)
        except Exception as e:
            logger.error("Quick screen failed for %s: %s", ticker, e)
            return "HOLD"
