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
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from stock_trading_system.utils import get_logger

logger = get_logger("agents.analyzer")


# Pipeline step definitions shared between backend and frontend.
# Each entry: (step_id, human-readable label, state field it produces).
# Investment debate / risk assessment / trader decision each live on nested
# state dicts rather than plain strings, so we treat their *_state keys as
# the completion signal.
PIPELINE_STEPS: list[tuple[str, str, str]] = [
    ("market", "技术面分析", "market_report"),
    ("social", "情绪分析", "sentiment_report"),
    ("news", "新闻分析", "news_report"),
    ("fundamentals", "基本面分析", "fundamentals_report"),
    ("debate", "多空辩论", "investment_debate_state"),
    ("risk", "风险评估", "risk_debate_state"),
    ("decision", "最终决策", "final_trade_decision"),
]


def _is_step_done(state: dict, state_key: str) -> bool:
    """Return True if this step's output has been populated in state."""
    if not isinstance(state, dict):
        return False
    val = state.get(state_key)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, dict):
        # debate/risk states have multiple sub-fields; "history" or
        # "current_response" being non-empty is a reasonable done signal.
        return any(bool(v) for v in val.values())
    return bool(val)


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
    steps: list = field(default_factory=list)  # list of {id, label, status, duration_ms}


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

        # Set API key in environment BEFORE creating the graph
        api_key = gemini_config.get("api_key", "")
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key

        ta_config = DEFAULT_CONFIG.copy()
        ta_config["llm_provider"] = "google"
        ta_config["deep_think_llm"] = gemini_config.get("deep_think_model", "gemini-3.1-pro-preview")
        ta_config["quick_think_llm"] = gemini_config.get("model", "gemini-2.5-flash")
        ta_config["google_thinking_level"] = gemini_config.get("thinking_level", "high")
        ta_config["output_language"] = "Chinese"
        # Remove OpenAI backend_url default — let Google client use its own default endpoint
        ta_config["backend_url"] = None

        self._graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True,
            config=ta_config,
        )
        logger.info("TradingAgents graph initialized with Gemini")

    def analyze(
        self,
        ticker: str,
        date: str,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> AnalysisResult:
        """Run full multi-agent analysis on a stock.

        Args:
            ticker: Stock symbol (e.g. "AAPL")
            date: Analysis date "YYYY-MM-DD"
            progress_cb: Optional callback invoked with step events. Each call
                receives a dict like ``{"type": "step_done", "step": "market",
                "label": "技术面分析", "duration_ms": 12345, "index": 0,
                "total": 7}``. Event types: ``pipeline_start``, ``step_start``,
                ``step_done``, ``pipeline_done``, ``pipeline_error``.

        Returns:
            AnalysisResult with signal, reports, decision details and per-step
            timings.
        """
        self._init_graph()

        logger.info("Starting analysis for %s on %s", ticker, date)
        total = len(PIPELINE_STEPS)

        def emit(event: dict):
            if progress_cb:
                try:
                    progress_cb(event)
                except Exception as e:
                    logger.warning("progress_cb failed: %s", e)

        # Track per-step start time + duration. Steps are marked "running" as
        # soon as the previous one completes (best-effort — the graph may run
        # some steps in parallel, but the user-facing view is still useful).
        step_status: dict[str, dict] = {
            sid: {"id": sid, "label": label, "status": "pending", "duration_ms": 0}
            for sid, label, _ in PIPELINE_STEPS
        }
        step_starts: dict[str, float] = {}
        # Mark the first step as running immediately.
        if PIPELINE_STEPS:
            first_id = PIPELINE_STEPS[0][0]
            step_status[first_id]["status"] = "running"
            step_starts[first_id] = time.monotonic()

        emit({
            "type": "pipeline_start",
            "ticker": ticker,
            "date": date,
            "total": total,
            "steps": list(step_status.values()),
        })

        try:
            # Replicate TradingAgents.propagate()'s streaming loop so we can
            # peek at intermediate state between chunks and push progress to
            # the UI in real time.
            graph = self._graph
            init_state = graph.propagator.create_initial_state(ticker, date)
            args = graph.propagator.get_graph_args()

            last_state = init_state
            for chunk in graph.graph.stream(init_state, **args):
                last_state = chunk
                now = time.monotonic()
                # For each pipeline step, if its state field just became
                # non-empty, record completion and start the next step.
                for idx, (sid, label, state_key) in enumerate(PIPELINE_STEPS):
                    if step_status[sid]["status"] == "done":
                        continue
                    if _is_step_done(chunk, state_key):
                        dur = int((now - step_starts.get(sid, now)) * 1000)
                        step_status[sid]["status"] = "done"
                        step_status[sid]["duration_ms"] = dur
                        emit({
                            "type": "step_done",
                            "step": sid,
                            "label": label,
                            "index": idx,
                            "total": total,
                            "duration_ms": dur,
                        })
                        # Start the next pending step if any.
                        next_idx = idx + 1
                        if next_idx < total:
                            nid = PIPELINE_STEPS[next_idx][0]
                            if step_status[nid]["status"] == "pending":
                                step_status[nid]["status"] = "running"
                                step_starts[nid] = now
                                emit({
                                    "type": "step_start",
                                    "step": nid,
                                    "label": PIPELINE_STEPS[next_idx][1],
                                    "index": next_idx,
                                    "total": total,
                                })

            final_state = last_state
            # Mark any still-pending steps as done using the final state as a
            # fallback (the graph may have finished them in a bundled chunk).
            now = time.monotonic()
            for idx, (sid, label, state_key) in enumerate(PIPELINE_STEPS):
                if step_status[sid]["status"] != "done" and _is_step_done(final_state, state_key):
                    dur = int((now - step_starts.get(sid, now)) * 1000)
                    step_status[sid]["status"] = "done"
                    step_status[sid]["duration_ms"] = dur
                    emit({
                        "type": "step_done",
                        "step": sid,
                        "label": label,
                        "index": idx,
                        "total": total,
                        "duration_ms": dur,
                    })

            signal = graph.process_signal(final_state["final_trade_decision"])
            # Persist to TradingAgents' log store (propagate normally does this).
            try:
                graph._log_state(date, final_state)
            except Exception as log_err:
                logger.debug("graph._log_state failed: %s", log_err)
            graph.curr_state = final_state

        except Exception as e:
            # Mark the current running step as failed so the UI can highlight.
            for sid, st in step_status.items():
                if st["status"] == "running":
                    st["status"] = "failed"
                    break
            emit({"type": "pipeline_error", "error": str(e), "steps": list(step_status.values())})
            raise

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
            steps=list(step_status.values()),
        )
        emit({
            "type": "pipeline_done",
            "ticker": ticker,
            "steps": result.steps,
            "signal": result.signal,
        })
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
