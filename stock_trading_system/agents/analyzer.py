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

v1.0.2 concurrency / state-isolation refactor (2026-05-07):
- ``_init_graph(user_id, depth) -> graph`` returns a local graph
  reference. Concurrent ``analyze()`` calls each hold their own graph
  variable so user A's analysis can't see user B's mid-flight state.
- ``self._graph`` / ``self._depth_override`` / ``self._active_user_id``
  shared mutable per-call attrs are removed (or kept only for legacy
  ``quick_screen`` which is single-tenant).
- OpenRouter provider routing is stashed in a module-level
  ``contextvars.ContextVar`` (``_OR_ROUTING_CTX``) that ``_init_graph``
  sets before ``TradingAgentsGraph(config=...)``; the factory patch
  reads from the ContextVar instead of calling ``get_config()`` —
  thread-local + test-friendly.
"""

import contextvars
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from stock_trading_system.utils import get_logger

logger = get_logger("agents.analyzer")


# v1.0.2 — per-call OR routing context.
#
# Set by ``_init_graph`` immediately before constructing
# ``TradingAgentsGraph(config=ta_config)``; consumed by the factory
# patch wrapper that runs synchronously inside that call. Each thread /
# task has its own context so two concurrent ``analyze()`` calls with
# different presets don't bleed routing parameters between each other.
#
# Shape: ``{"deep_model", "quick_model", "deep_provider_order",
#         "quick_provider_order", "headers"}`` or ``None``.
_OR_ROUTING_CTX: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "stockai_or_routing", default=None,
)


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


def _canonical_signal(trade_decision, *, fallback: str) -> str:
    """Resolve the canonical signal stored on the analysis row.

    Prefers the trader's explicit ``FINAL TRANSACTION PROPOSAL: **X**``
    via :func:`extract_trade_action`. Falls back to whatever
    ``graph.process_signal`` returned (typically OVERWEIGHT /
    UNDERWEIGHT, which extract_trade_action intentionally doesn't
    classify) when no clean BUY/SELL/HOLD pattern is present.
    """
    from stock_trading_system.agents.iterative.signal_extractor import (
        extract_trade_action,
    )
    parsed = extract_trade_action(trade_decision)
    return parsed if parsed else fallback


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
        """Monkey-patch TradingAgents factory to accept 'qwen'/'dashscope' providers
        AND inject OpenRouter ``extra_body.provider.order`` / ``default_headers``
        per active preset.

        Two pieces:

        1. **Qwen / DashScope** registration — the upstream factory only knows
           openai / anthropic / google / xai / ollama / openrouter. DashScope
           uses an OpenAI-compatible endpoint, so we register it as a custom
           provider in the same OpenAIClient (without ``use_responses_api``).

        2. **OpenRouter cross-vendor routing** (v1.0.1 fix) — upstream
           ``_PASSTHROUGH_KWARGS`` doesn't include ``extra_body`` or
           ``default_headers``, and ``_get_provider_kwargs`` returns ``{}``
           for openrouter — so the analyzer's main 7-agent path was hitting
           OR's primary endpoint without honoring the preset's
           ``provider_order``. The patch:

           * Extends ``_PASSTHROUGH_KWARGS`` to forward ``extra_body`` and
             ``default_headers`` through ``OpenAIClient.get_llm()``.
           * Wraps ``create_llm_client`` so OR calls receive
             ``extra_body.provider = {"order": [...], "allow_fallbacks": True}``
             matched per-model: when ``model`` matches the active deep
             preset's model id, deep's provider_order is used; same for
             quick. Headers (HTTP-Referer / X-Title) ride along too.

        Idempotent — safe to call multiple times.
        """
        _MAINLAND_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        try:
            from tradingagents.llm_clients import factory as _factory
            from tradingagents.llm_clients import openai_client as _oc

            already_patched = bool(getattr(_factory, "_stockai_patched", False))

            # ── Qwen / DashScope provider registration ───────────────
            existing = getattr(_oc, "_PROVIDER_CONFIG", {}).get("qwen")
            if existing != (_MAINLAND_URL, "DASHSCOPE_API_KEY"):
                _oc._PROVIDER_CONFIG["qwen"] = (_MAINLAND_URL, "DASHSCOPE_API_KEY")
                _oc._PROVIDER_CONFIG["dashscope"] = (_MAINLAND_URL, "DASHSCOPE_API_KEY")

            # ── _PASSTHROUGH_KWARGS extension for OR ─────────────────
            # Add extra_body + default_headers so ChatOpenAI sees them.
            current_kwargs = tuple(_oc._PASSTHROUGH_KWARGS)
            for extra in ("extra_body", "default_headers"):
                if extra not in current_kwargs:
                    current_kwargs = current_kwargs + (extra,)
            _oc._PASSTHROUGH_KWARGS = current_kwargs

            if already_patched:
                return

            # ── create_llm_client wrapper ────────────────────────────
            _orig = _factory.create_llm_client

            def _patched(provider, model, base_url=None, **kwargs):
                p = provider.lower()
                if p in ("qwen", "dashscope"):
                    return _oc.OpenAIClient(model, base_url, provider=p, **kwargs)

                # OR: inject extra_body.provider.order matched per-model.
                # v1.0.2 — read from the per-call ContextVar set by
                # ``_init_graph`` immediately before
                # ``TradingAgentsGraph(config=...)``. Pre-v1.0.2 we
                # called ``get_config()`` here, which broke under tests
                # that pass custom configs to ``StockAnalyzer(...)`` and
                # would silently break a future per-user preset feature
                # (the global config singleton is one user's view).
                #
                # If the ContextVar is unset (legacy / non-OR caller)
                # we just pass through unchanged.
                if p == "openrouter":
                    try:
                        routing = _OR_ROUTING_CTX.get()
                    except LookupError:
                        routing = None
                    if routing:
                        order: list[str] = []
                        if model == routing.get("deep_model"):
                            order = routing.get("deep_provider_order") or []
                        elif model == routing.get("quick_model"):
                            order = routing.get("quick_provider_order") or []
                        if order:
                            existing_extra = dict(kwargs.get("extra_body") or {})
                            existing_extra["provider"] = {
                                "order": list(order),
                                "allow_fallbacks": True,
                            }
                            kwargs["extra_body"] = existing_extra
                        headers = routing.get("headers") or {}
                        if headers and "default_headers" not in kwargs:
                            kwargs["default_headers"] = dict(headers)

                return _orig(provider, model, base_url, **kwargs)

            _factory.create_llm_client = _patched
            _factory._stockai_patched = True
            logger.info(
                "Patched TradingAgents factory for Qwen/DashScope + OR provider_order",
            )
        except Exception as e:
            logger.warning("Failed to patch TradingAgents factory: %s", e)

    def _init_graph(
        self,
        user_id: int | None = None,
        depth: str = "standard",
    ):
        """Lazy-init TradingAgents graph, cached per active provider.

        Returns the constructed graph as a **local reference**. Concurrent
        ``analyze()`` calls each receive their own returned graph and
        pass it through to internal helpers — no per-call state lives
        on ``self``.

        Cache key (v1.0.1 + v1.0.2):
        - qwen / gemini: ``"<provider>@<user_id|global>"``.
        - openrouter:    ``"openrouter:<deep_id>:<quick_id>@<user_id|global>"``.

        Switching providers / OR presets / users creates a fresh graph;
        switching back hits the cache.

        ``self._graph`` is set to the most recently-built graph for the
        legacy ``quick_screen`` code path (single-tenant, not concurrent),
        but ``analyze()`` does NOT read it — it uses the local return.
        """
        from stock_trading_system.llm.router import get_active_provider

        provider = get_active_provider(self._config, user_id=user_id)
        scope = str(user_id) if user_id is not None else "global"

        if provider == "openrouter":
            from stock_trading_system.llm.router import resolve_openrouter_model
            deep  = resolve_openrouter_model(self._config, role="deep")
            quick = resolve_openrouter_model(self._config, role="quick")
            cache_key = f"openrouter:{deep['id']}:{quick['id']}@{scope}"
        else:
            cache_key = f"{provider or ''}@{scope}"

        with self._graph_lock:
            if cache_key in self._graphs:
                cached = self._graphs[cache_key]
                self._graph = cached  # legacy compat for quick_screen
                return cached

            self._patch_tradingagents_qwen()

            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.default_config import DEFAULT_CONFIG

            ta_config = DEFAULT_CONFIG.copy()
            ta_config["output_language"] = "Chinese"
            ta_config["llm_timeout"] = 120

            or_routing: dict | None = None
            if provider == "qwen":
                self._configure_qwen(ta_config)
            elif provider == "openrouter":
                or_routing = self._configure_openrouter(ta_config)
            else:
                self._configure_gemini(ta_config)

            # Inject active prompt overrides from prompt_store
            # (iteration phase 2). v1.0.2 — read iteration toggle from
            # local depth, not self._depth_override.
            if self._is_iteration_enabled(depth):
                agent_prompts = self._load_active_prompts()
                if agent_prompts:
                    ta_config["agent_prompts"] = agent_prompts

            # v1.0.2 — set ContextVar so the patched factory wrapper
            # reads OR routing for *this* graph init only. The token
            # is reset in ``finally`` so concurrent analyze() calls
            # never see each other's routing.
            token = (
                _OR_ROUTING_CTX.set(or_routing)
                if or_routing is not None
                else None
            )
            try:
                graph = TradingAgentsGraph(
                    selected_analysts=["market", "social", "news", "fundamentals"],
                    debug=True,
                    config=ta_config,
                )
            finally:
                if token is not None:
                    _OR_ROUTING_CTX.reset(token)

            self._graphs[cache_key] = graph
            self._graph = graph  # legacy compat
            logger.info(
                "TradingAgents graph initialized with %s (key=%s)",
                provider, cache_key,
            )
            return graph

    def _iteration_for(self, depth: str) -> bool:
        """Per-call iteration toggle (replaces the v1.0.1
        ``_iteration_enabled`` property which read ``self._depth_override``).

        depth:
            quick    → force off (single-pass)
            deep     → force on (when iteration code is available)
            standard → fall back to ``config.iteration.enabled``
        """
        cfg_enabled = bool(self._config.get("iteration", {}).get("enabled", False))
        if depth == "quick":
            return False
        if depth == "deep":
            return True
        return cfg_enabled

    # Back-compat alias used by ``_init_graph``. New code should call
    # ``_iteration_for(depth)`` directly.
    def _is_iteration_enabled(self, depth: str) -> bool:
        return self._iteration_for(depth)

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

    def _configure_openrouter(self, ta_config: dict) -> dict:
        """Wire TradingAgents to use OpenRouter as the LLM provider.

        Sets the basic ta_config fields upstream TradingAgents reads
        directly (``llm_provider`` / ``deep_think_llm`` / ``quick_think_llm``
        / ``backend_url``) and **returns a per-call routing dict**
        carrying:

        - ``deep_model`` / ``quick_model`` — model ids the factory
          patch matches against to differentiate deep vs quick calls.
        - ``deep_provider_order`` / ``quick_provider_order`` — vendor
          fallback chains per role. Fed into
          ``extra_body.provider.order`` with ``allow_fallbacks=True``.
        - ``headers`` — HTTP-Referer / X-Title for OR analytics.

        v1.0.2 (2026-05-07): ``provider_order`` IS now injected into
        the actual TradingAgents path — pre-v1.0.2 the docstring said
        "provider_order intentionally NOT injected" because upstream
        ``_PASSTHROUGH_KWARGS`` didn't include ``extra_body``. v1.0.1
        added the passthrough; v1.0.2 finishes the refactor by routing
        the lookup through a ContextVar instead of ``get_config()``
        so test configs / future per-user presets land on the right
        graph.

        The caller (``_init_graph``) sets ``_OR_ROUTING_CTX`` to the
        returned dict immediately before calling
        ``TradingAgentsGraph(config=ta_config)``; the factory patch
        wrapper reads it during deep + quick client construction and
        resets it on exit.
        """
        from stock_trading_system.llm.router import resolve_openrouter_model

        or_cfg = self._config.get("openrouter", {}) or {}
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or or_cfg.get("api_key", "")
        )
        if not api_key:
            raise RuntimeError(
                "llm_provider=openrouter but openrouter.api_key is empty"
            )
        # Upstream factory reads from env, not from the config dict.
        os.environ["OPENROUTER_API_KEY"] = api_key

        deep  = resolve_openrouter_model(self._config, role="deep")
        quick = resolve_openrouter_model(self._config, role="quick")

        ta_config["llm_provider"]    = "openrouter"  # see _PROVIDER_CONFIG in upstream openai_client.py
        ta_config["deep_think_llm"]  = deep["model"]
        ta_config["quick_think_llm"] = quick["model"]
        ta_config["backend_url"]     = or_cfg.get(
            "base_url", "https://openrouter.ai/api/v1")
        # Deep timeout = 10min (long reasoning chains); quick = 2min.
        ta_config["llm_deep_kwargs"]  = {"timeout": 600}
        ta_config["llm_quick_kwargs"] = {"timeout": 120}

        headers: dict = {}
        if or_cfg.get("http_referer"):
            headers["HTTP-Referer"] = or_cfg["http_referer"]
        if or_cfg.get("x_title"):
            headers["X-Title"] = or_cfg["x_title"]
        if headers:
            ta_config["llm_default_headers"] = headers

        # Routing dict for the factory wrapper — handed back to the
        # caller so ``_init_graph`` can stash it in the ContextVar
        # for THIS thread / call only.
        return {
            "deep_model":            deep["model"],
            "quick_model":           quick["model"],
            "deep_provider_order":   list(deep.get("provider_order") or []),
            "quick_provider_order":  list(quick.get("provider_order") or []),
            "headers":               dict(headers),
        }

    def _build_quick_llm(self, user_id: int | None = None):
        """Build a quick-think LangChain chat instance for the active provider.

        Used by :class:`RenderingExtractor` to convert the finished reports
        into per-tab structured cards. Mirrors the model selection in
        ``_configure_qwen`` / ``_configure_openrouter`` / ``_configure_gemini``
        so structured output uses the same model that produced the
        underlying text.

        v1.0.2 — ``user_id`` is an explicit param (was a hidden read of
        ``self._active_user_id`` in v1.0.1, which was unsafe under
        concurrent analyze() calls). Pass the same user_id you passed
        to ``_init_graph`` so the quick LLM lands on the same provider
        scope as the deep analysis.
        """
        from stock_trading_system.llm.router import get_active_provider

        provider = get_active_provider(self._config, user_id=user_id)
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
        if provider == "openrouter":
            from langchain_openai import ChatOpenAI
            from stock_trading_system.llm.router import resolve_openrouter_model

            or_cfg = self._config.get("openrouter", {}) or {}
            api_key = (
                os.environ.get("OPENROUTER_API_KEY")
                or or_cfg.get("api_key", "")
            )
            preset = resolve_openrouter_model(self._config, role="quick")

            headers: dict = {}
            if or_cfg.get("http_referer"):
                headers["HTTP-Referer"] = or_cfg["http_referer"]
            if or_cfg.get("x_title"):
                headers["X-Title"] = or_cfg["x_title"]

            extra_body: dict = {}
            if preset["provider_order"]:
                extra_body["provider"] = {
                    "order": preset["provider_order"],
                    "allow_fallbacks": True,
                }

            return ChatOpenAI(
                model=preset["model"],
                api_key=api_key,
                base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                default_headers=headers or None,
                temperature=0,
                timeout=60,
                extra_body=extra_body or None,
                **preset.get("kwargs", {}),
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
        user_id: int | None = None,
    ) -> None:
        """Best-effort extraction of structured per-tab cards into ``result.rendering``.

        Failures here MUST NOT block the analysis task — the markdown
        reports are the canonical artefact and the UI falls back to them
        when ``rendering`` is empty or partial.

        v1.0.2 — ``user_id`` is an explicit param so the quick LLM
        lands on the same per-user provider scope as the deep graph
        that produced the reports.
        """
        try:
            from stock_trading_system.agents.rendering.extractor import (
                RenderingExtractor,
            )
            extractor = RenderingExtractor(
                self._build_quick_llm(user_id=user_id),
                data_manager=self._get_data_manager(),
            )
            result.rendering = extractor.extract(result, ticker=ticker)
            # Clear any stale error from a previous in-process retry.
            result.rendering_error = None
        except Exception as e:  # noqa: BLE001
            # v1.7 — surface the failure reason on the result so the
            # worker can persist it as ``rendering_error`` for the UI
            # banner / retry button. Truncate to 240 chars and use the
            # exception class + message; never include report bodies.
            err_msg = f"{type(e).__name__}: {e}"[:240]
            logger.warning("rendering extraction skipped: %s", err_msg)
            result.rendering = {}
            result.rendering_error = err_msg

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
        user_id: int | None = None,
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
            user_id: Per-user provider scope (v1.0.1). When set, the graph
                resolves the active LLM provider via the per-user
                ``user_settings.llm_provider`` row before falling back to
                global config. The cache key includes the resolved
                provider so users with different settings don't share a
                graph. None → fall back to global resolution (existing
                behaviour for callers that haven't been updated).

        Returns:
            AnalysisResult with signal, reports, decision details and per-step
            timings.
        """
        depth = depth if depth in ("quick", "standard", "deep") else "standard"
        # v1.0.2 — _init_graph returns a *local* graph reference. We
        # store it in ``graph`` and pass it into helpers; no per-call
        # state lives on ``self`` so concurrent analyze() calls can't
        # corrupt each other's user_id / depth / graph bindings.
        graph = self._init_graph(user_id=user_id, depth=depth)
        # Track per-call iteration flag locally (legacy
        # _iteration_enabled property removed in v1.0.2).
        iteration_enabled = self._iteration_for(depth)

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
            if iteration_enabled:
                final_state, signal = self._run_with_weights(ticker, date, graph)
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
                final_signal = _canonical_signal(
                    final_state.get("final_trade_decision"),
                    fallback=str(signal),
                )
                result = AnalysisResult(
                    ticker=ticker,
                    signal=final_signal,
                    market_report=final_state.get("market_report", ""),
                    sentiment_report=final_state.get("sentiment_report", ""),
                    news_report=final_state.get("news_report", ""),
                    fundamentals_report=final_state.get("fundamentals_report", ""),
                    investment_debate=final_state.get("investment_debate_state", {}),
                    risk_assessment=final_state.get("risk_debate_state", {}),
                    trade_decision=final_state.get("final_trade_decision", {}),
                    steps=list(step_status.values()),
                )
                self._maybe_extract_rendering(result, ticker=ticker, user_id=user_id)
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
            # the UI in real time. v1.0.2 — ``graph`` is the local var
            # from ``_init_graph(user_id, depth)`` above; never read
            # ``self._graph`` here so concurrent calls can't corrupt
            # this read.
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

        # v1.20: prefer the trader's explicit ``FINAL TRANSACTION
        # PROPOSAL: **X**`` over ``graph.process_signal``'s separate LLM
        # classification. The two used to drift, surfacing as the
        # "顶部 Hold, 决策正文 Sell" inconsistency on the detail page.
        final_signal = _canonical_signal(
            final_state.get("final_trade_decision"),
            fallback=str(signal),
        )
        result = AnalysisResult(
            ticker=ticker,
            signal=final_signal,
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
        self, ticker: str, date: str, graph=None,
    ) -> tuple[dict[str, Any], Any]:
        """Bypass propagate() to inject weight context into init_state.

        v1.0.2 — ``graph`` is now passed in by ``analyze()`` so this
        helper doesn't read ``self._graph`` (concurrent-call safety).
        Falls back to ``self._graph`` when called without an explicit
        graph (legacy callers / tests that haven't been migrated).
        """
        from stock_trading_system.agents.iterative.config import load_iteration_config

        iter_config = load_iteration_config(self._config.get("iteration", {}))

        if graph is None:
            graph = self._graph  # legacy compat path

        # Build initial state via the propagator
        init_state = graph.propagator.create_initial_state(ticker, date)

        # Inject weight context if a scorer is available
        if iter_config.darwinian.enabled:
            weight_text = self._get_weight_context()
            if weight_text:
                init_state["messages"].insert(0, ("system", weight_text))

        # Run graph (preserve debug stream behaviour)
        args = graph.propagator.get_graph_args()
        if graph.debug:
            trace: list[dict] = []
            for chunk in graph.graph.stream(init_state, **args):
                if chunk.get("messages"):
                    chunk["messages"][-1].pretty_print()
                trace.append(chunk)
            final_state = trace[-1] if trace else {}
        else:
            final_state = graph.graph.invoke(init_state, **args)

        signal = graph.process_signal(
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
