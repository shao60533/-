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
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

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
    # v1.19: per-tab structured cards for the 8-tab UI. Keys are the tab
    # identifiers (``summary`` / ``Market`` / ...); values are dicts that
    # match the corresponding Pydantic schema in
    # ``stock_trading_system.agents.rendering.schemas`` — or ``None`` when
    # extraction failed for that tab (frontend falls back to markdown).
    rendering: dict = field(default_factory=dict)


class StockAnalyzer:
    """Wraps TradingAgents for multi-agent stock analysis using Gemini."""

    def __init__(self, config: dict):
        self._config = config
        self._graph = None
        self._graphs: dict[str, Any] = {}
        self._graph_lock = threading.Lock()

    @staticmethod
    def _patch_tradingagents_qwen():
        """Monkey-patch TradingAgents factory to accept 'qwen'/'dashscope' providers.

        The upstream factory only knows openai/anthropic/google/xai/ollama/openrouter.
        DashScope uses an OpenAI-compatible endpoint, so we register it as a custom
        provider in the same OpenAIClient, but WITHOUT use_responses_api.
        Idempotent — safe to call multiple times.
        """
        _MAINLAND_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        try:
            from tradingagents.llm_clients import factory as _factory
            from tradingagents.llm_clients import openai_client as _oc
            existing = getattr(_oc, "_PROVIDER_CONFIG", {}).get("qwen")
            if existing == (_MAINLAND_URL, "DASHSCOPE_API_KEY"):
                return
            _oc._PROVIDER_CONFIG["qwen"] = (_MAINLAND_URL, "DASHSCOPE_API_KEY")
            _oc._PROVIDER_CONFIG["dashscope"] = (_MAINLAND_URL, "DASHSCOPE_API_KEY")
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
        """Lazy-init TradingAgents graph, cached per active provider.

        Cache key is the active LLM provider name (``"qwen"``/``"gemini"``).
        Switching providers creates a fresh graph; switching back hits the
        cache. Model bumps within the same provider don't bust the cache —
        TradingAgentsGraph rebinds the model lazily, so a per-provider entry
        is sufficient.
        """
        from stock_trading_system.llm.router import get_active_provider

        provider = get_active_provider(self._config)
        cache_key = provider or ""

        with self._graph_lock:
            if cache_key in self._graphs:
                self._graph = self._graphs[cache_key]
                return

            self._patch_tradingagents_qwen()

            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.default_config import DEFAULT_CONFIG

            ta_config = DEFAULT_CONFIG.copy()
            ta_config["output_language"] = "Chinese"
            ta_config["llm_timeout"] = 120

            if provider == "qwen":
                self._configure_qwen(ta_config)
            else:
                self._configure_gemini(ta_config)

            # Inject active prompt overrides from prompt_store (iteration phase 2)
            if self._iteration_enabled:
                agent_prompts = self._load_active_prompts()
                if agent_prompts:
                    ta_config["agent_prompts"] = agent_prompts

            graph = TradingAgentsGraph(
                selected_analysts=["market", "social", "news", "fundamentals"],
                debug=True,
                config=ta_config,
            )
            self._graphs[cache_key] = graph
            self._graph = graph
            logger.info("TradingAgents graph initialized with %s (key=%s)", provider, cache_key)

    @property
    def _iteration_enabled(self) -> bool:
        """Whether to run the iterative / Darwinian-weighted pipeline.

        ``analyze(depth=...)`` sets ``self._depth_override`` for the
        duration of one call:
            quick    → force off (single-pass)
            deep     → force on (when iteration code is available)
            standard → fall back to the config flag
        """
        cfg_enabled = bool(self._config.get("iteration", {}).get("enabled", False))
        depth = getattr(self, "_depth_override", None) or "standard"
        if depth == "quick":
            return False
        if depth == "deep":
            return True
        return cfg_enabled

    def _configure_qwen(self, ta_config: dict) -> None:
        qwen_config = self._config.get("qwen", {})
        qwen_key = qwen_config.get("api_key", "")
        if not qwen_key:
            raise RuntimeError("llm_provider=qwen but qwen.api_key is empty")
        os.environ["DASHSCOPE_API_KEY"] = qwen_key
        model = qwen_config.get("model", "qwen-plus")
        ta_config["llm_provider"] = "qwen"
        ta_config["deep_think_llm"] = qwen_config.get("deep_think_model", model)
        ta_config["quick_think_llm"] = model
        ta_config["backend_url"] = qwen_config.get(
            "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        ta_config["llm_deep_kwargs"] = {"extra_body": {"enable_thinking": True}, "timeout": 600}
        ta_config["llm_quick_kwargs"] = {"extra_body": {"enable_thinking": False}, "timeout": 120}

    def _build_quick_llm(self):
        """Build a quick-think LangChain chat instance for the active provider.

        Used by :class:`RenderingExtractor` to convert the finished reports
        into per-tab structured cards. Mirrors the model selection in
        ``_configure_qwen`` / ``_configure_gemini`` so structured output uses
        the same model that produced the underlying text.
        """
        from stock_trading_system.llm.router import get_active_provider

        provider = get_active_provider(self._config)
        if provider == "qwen":
            from langchain_openai import ChatOpenAI
            qcfg = self._config.get("qwen", {}) or {}
            return ChatOpenAI(
                model=qcfg.get("model", "qwen-plus"),
                api_key=qcfg.get("api_key", ""),
                base_url=qcfg.get(
                    "base_url",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
                temperature=0,
                timeout=60,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        gcfg = self._config.get("gemini", {}) or {}
        return ChatGoogleGenerativeAI(
            model=gcfg.get("model", "gemini-2.5-flash"),
            api_key=gcfg.get("api_key", ""),
            temperature=0,
            timeout=60,
        )

    def _get_data_manager(self):
        """Lazy-construct a DataManager for hybrid News/Fundamentals extraction.

        Lazy import avoids the web.app circular dependency that bites the
        worker thread on first analysis. Returns ``None`` on any boot
        failure so the extractor falls back to pure-LLM mode for those
        two tabs (the other six are unaffected).
        """
        try:
            from stock_trading_system.data.data_manager import DataManager
            return DataManager(self._config)
        except Exception as e:  # noqa: BLE001
            logger.warning("data_manager init failed: %s", e)
            return None

    def _maybe_extract_rendering(
        self, result: "AnalysisResult", ticker: str = "",
    ) -> None:
        """Best-effort extraction of structured per-tab cards into ``result.rendering``.

        Failures here MUST NOT block the analysis task — the markdown
        reports are the canonical artefact and the UI falls back to them
        when ``rendering`` is empty or partial.
        """
        try:
            from stock_trading_system.agents.rendering.extractor import (
                RenderingExtractor,
            )
            extractor = RenderingExtractor(
                self._build_quick_llm(),
                data_manager=self._get_data_manager(),
            )
            result.rendering = extractor.extract(result, ticker=ticker)
        except Exception as e:  # noqa: BLE001
            logger.warning("rendering extraction skipped: %s", e)
            result.rendering = {}

    def _configure_gemini(self, ta_config: dict) -> None:
        gemini_config = self._config.get("gemini", {})
        gemini_key = gemini_config.get("api_key", "")
        if not gemini_key:
            raise RuntimeError("llm_provider=gemini but gemini.api_key is empty")
        os.environ["GOOGLE_API_KEY"] = gemini_key
        os.environ["GEMINI_API_KEY"] = gemini_key
        import httpx as _httpx
        ta_config["llm_client_args"] = {"http2": False, "transport": _httpx.HTTPTransport(retries=3)}
        for _var in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
            os.environ.pop(_var, None)
        ta_config["llm_provider"] = "google"
        ta_config["deep_think_llm"] = gemini_config.get("deep_think_model", "gemini-2.5-flash")
        ta_config["quick_think_llm"] = gemini_config.get("model", "gemini-2.5-flash")
        ta_config["google_thinking_level"] = gemini_config.get("thinking_level", "low")
        ta_config["backend_url"] = None

    def analyze(
        self,
        ticker: str,
        date: str,
        progress_cb: Optional[Callable[[dict], None]] = None,
        depth: str = "standard",
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
            depth: ``quick`` / ``standard`` / ``deep``. Drives the iteration
                toggle: ``quick`` forces single-pass (no reflection), ``deep``
                forces iteration on (where available), ``standard`` defers to
                the config flag. Unknown values fall back to ``standard``.

        Returns:
            AnalysisResult with signal, reports, decision details and per-step
            timings.
        """
        depth = depth if depth in ("quick", "standard", "deep") else "standard"
        self._depth_override: str | None = depth
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
            # Iteration mode: delegate to _run_with_weights which handles
            # Darwinian weight-context injection + prompt overrides. Skips the
            # streaming progress view but still emits pipeline_done.
            if self._iteration_enabled:
                final_state, signal = self._run_with_weights(ticker, date)
                # Mark all steps done in a single bulk emit so the UI gets a
                # best-effort completion view.
                now = time.monotonic()
                for idx, (sid, label, state_key) in enumerate(PIPELINE_STEPS):
                    if _is_step_done(final_state, state_key):
                        step_status[sid]["status"] = "done"
                        step_status[sid]["duration_ms"] = 0
                        emit({
                            "type": "step_done",
                            "step": sid,
                            "label": label,
                            "index": idx,
                            "total": total,
                            "duration_ms": 0,
                        })
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
                self._maybe_extract_rendering(result, ticker=ticker)
                emit({
                    "type": "pipeline_done",
                    "ticker": ticker,
                    "steps": result.steps,
                    "signal": result.signal,
                })
                logger.info("Analysis complete (iteration) for %s: signal=%s", ticker, signal)
                return result

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
        self._maybe_extract_rendering(result, ticker=ticker)
        emit({
            "type": "pipeline_done",
            "ticker": ticker,
            "steps": result.steps,
            "signal": result.signal,
        })
        logger.info("Analysis complete for %s: signal=%s", ticker, signal)
        return result

    def _run_with_weights(
        self, ticker: str, date: str,
    ) -> tuple[dict[str, Any], Any]:
        """Bypass propagate() to inject weight context into init_state."""
        from stock_trading_system.agents.iterative.config import load_iteration_config

        iter_config = load_iteration_config(self._config.get("iteration", {}))

        # Build initial state via the propagator
        init_state = self._graph.propagator.create_initial_state(ticker, date)

        # Inject weight context if a scorer is available
        if iter_config.darwinian.enabled:
            weight_text = self._get_weight_context()
            if weight_text:
                init_state["messages"].insert(0, ("system", weight_text))

        # Run graph (preserve debug stream behaviour)
        args = self._graph.propagator.get_graph_args()
        if self._graph.debug:
            trace: list[dict] = []
            for chunk in self._graph.graph.stream(init_state, **args):
                if chunk.get("messages"):
                    chunk["messages"][-1].pretty_print()
                trace.append(chunk)
            final_state = trace[-1] if trace else {}
        else:
            final_state = self._graph.graph.invoke(init_state, **args)

        signal = self._graph.process_signal(
            final_state.get("final_trade_decision", "")
        )
        return final_state, signal

    def _get_weight_context(self) -> str:
        """Return formatted weight context from the scorer singleton, if any."""
        try:
            from stock_trading_system.agents.iterative.darwinian import format_weight_context
            from stock_trading_system.agents.iterative.agent_scorer import AgentScorer
            from stock_trading_system.agents.iterative.config import load_iteration_config

            iter_config = load_iteration_config(self._config.get("iteration", {}))
            db_path = self._config.get("portfolio", {}).get("db_path", "data/portfolio.db")
            scorer = AgentScorer(db_path, iter_config)
            return format_weight_context(scorer)
        except Exception as e:
            logger.warning("Could not load weight context: %s", e)
            return ""

    def _load_active_prompts(self) -> dict[str, dict[str, str]]:
        """Load active prompt overrides from the prompt_versions table.

        Returns a dict suitable for ta_config["agent_prompts"]:
          {agent_id: {"system_prompt": ...} | {"prompt_prefix": ...}}
        """
        try:
            from stock_trading_system.agents.iterative.prompt_store import PromptStore

            db_path = self._config.get("portfolio", {}).get("db_path", "data/portfolio.db")
            store = PromptStore(db_path)
            active = store.get_all_active_prompts()
            if not active:
                return {}

            result: dict[str, dict[str, str]] = {}
            for agent_id, row in active.items():
                prompt_type = row.get("prompt_type", "system_prompt")
                result[agent_id] = {prompt_type: row["prompt_text"]}
            return result
        except Exception as e:
            logger.warning("Could not load active prompts: %s", e)
            return {}

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
