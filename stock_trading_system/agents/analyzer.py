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
    """Wraps TradingAgents for multi-agent stock analysis (Gemini or Qwen)."""

    def __init__(self, config: dict):
        self._config = config
        self._graph = None

    @staticmethod
    def _patch_tradingagents_qwen():
        """Monkey-patch TradingAgents factory to accept 'qwen'/'dashscope' providers.

        The upstream factory only knows openai/anthropic/google/xai/ollama/openrouter.
        DashScope uses an OpenAI-compatible endpoint, so we register it as a custom
        provider in the same OpenAIClient, but WITHOUT use_responses_api.
        Idempotent — safe to call multiple times.
        """
        try:
            from tradingagents.llm_clients import factory as _factory
            from tradingagents.llm_clients import openai_client as _oc
            if "qwen" in getattr(_oc, "_PROVIDER_CONFIG", {}):
                return  # already patched
            _oc._PROVIDER_CONFIG["qwen"] = (
                "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY")
            _oc._PROVIDER_CONFIG["dashscope"] = (
                "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY")
            _orig = _factory.create_llm_client

            def _patched(provider, model, base_url=None, **kwargs):
                if provider.lower() in ("qwen", "dashscope"):
                    return _oc.OpenAIClient(model, base_url, provider=provider.lower(), **kwargs)
                return _orig(provider, model, base_url, **kwargs)

            _factory.create_llm_client = _patched
            logger.info("Patched TradingAgents factory for Qwen/DashScope")
        except Exception as e:
            logger.warning("Failed to patch TradingAgents for Qwen: %s", e)

    def _init_graph(self):
        """Lazy-init TradingAgents graph."""
        if self._graph is not None:
            return

        self._patch_tradingagents_qwen()

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        ta_config = DEFAULT_CONFIG.copy()
        ta_config["output_language"] = "Chinese"
        ta_config["llm_timeout"] = 120

        qwen_config = self._config.get("qwen", {})
        gemini_config = self._config.get("gemini", {})

        qwen_key = qwen_config.get("api_key", "")
        gemini_key = gemini_config.get("api_key", "")

        if qwen_key:
            # ── Qwen / DashScope (OpenAI-compatible) ──────────────────────────
            os.environ["DASHSCOPE_API_KEY"] = qwen_key
            model = qwen_config.get("model", "qwen-plus")
            ta_config["llm_provider"] = "qwen"
            ta_config["deep_think_llm"] = qwen_config.get("deep_think_model", model)
            ta_config["quick_think_llm"] = model
            ta_config["backend_url"] = qwen_config.get(
                "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            # Deep thinker (Judge / Trader / Risk Manager): enable Qwen3 thinking
            # for high-quality reasoning on final investment decisions.
            # Quick thinker (Market / News / Fundamentals data collectors): disable
            # thinking for fast data retrieval — no reasoning depth needed.
            ta_config["llm_deep_kwargs"] = {
                "extra_body": {"enable_thinking": True},
                "timeout": 600,   # 10 min — thinking on long context can be slow
            }
            ta_config["llm_quick_kwargs"] = {
                "extra_body": {"enable_thinking": False},
                "timeout": 120,
            }
            logger.info("Using Qwen LLM provider (model=%s, deep_thinking=ON)", model)
        else:
            # ── Google Gemini ─────────────────────────────────────────────────
            if gemini_key:
                os.environ["GOOGLE_API_KEY"] = gemini_key
                os.environ["GEMINI_API_KEY"] = gemini_key

            import httpx as _httpx

            # Disable HTTP/2 and add transport-level retries.
            # TUN-mode proxy (Clash/Surge) cold-starts the first TCP connection,
            # causing "Server disconnected" on the first call; retries fix this.
            ta_config["llm_client_args"] = {
                "http2": False,
                "transport": _httpx.HTTPTransport(retries=3),
            }
            # Clear proxy env vars — Gemini blocks HK exit IPs.
            for _var in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                         "all_proxy", "ALL_PROXY"):
                os.environ.pop(_var, None)

            ta_config["llm_provider"] = "google"
            ta_config["deep_think_llm"] = gemini_config.get("deep_think_model", "gemini-2.5-flash")
            ta_config["quick_think_llm"] = gemini_config.get("model", "gemini-2.5-flash")
            ta_config["google_thinking_level"] = gemini_config.get("thinking_level", "low")
            ta_config["backend_url"] = None
            logger.info("Using Gemini LLM provider (model=%s)", ta_config["quick_think_llm"])

        self._graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True,
            config=ta_config,
        )

    def analyze(self, ticker: str, date: str, progress_callback=None) -> AnalysisResult:
        """Run full multi-agent analysis on a stock.

        Args:
            ticker: Stock symbol (e.g. "AAPL")
            date: Analysis date "YYYY-MM-DD"
            progress_callback: Optional callable(step, status) for real-time progress

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
