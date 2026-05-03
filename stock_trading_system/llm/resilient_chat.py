"""Provider-fallback chat client builder.

Wraps the active provider's ChatModel with LangChain's
``with_fallbacks`` so a Gemini ``ResourceExhausted`` (or Qwen
``RateLimitError``) on a single request is silently retried on the
other provider — no exception ever bubbles up to the user-facing
"评估失败" path. Single-request scope: there is no state mutation,
no persistent provider switch, no edit to ``user_settings`` or env.

The returned Runnable supports ``.invoke()`` and
``.with_structured_output(Schema)`` because ``RunnableWithFallbacks``
inherits the Runnable interface (LangChain ≥ 0.3).

Three caller-visible helpers:
    * :func:`build_resilient_chat` — main factory.
    * :func:`get_fallback_counters` — telemetry snapshot.
    * :func:`reset_fallback_counters` — call once per task.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from stock_trading_system.llm.rate_limit import is_rate_limit_error
from stock_trading_system.llm.router import get_active_provider

logger = logging.getLogger("llm.resilient_chat")

ChatKind = Literal["quick", "deep"]

# Module-level fallback counter (telemetry only — we surface this on
# the V3 metrics + analysis result so operators can see how often the
# fallback fired during a task). Counters are deliberately shared
# across concurrent tasks; correctness lives elsewhere, this is just a
# count.
_fallback_counter: dict[str, int] = {
    "gemini→qwen": 0,
    "qwen→gemini": 0,
}


def get_fallback_counters() -> dict[str, int]:
    """Snapshot of fallback counters. Mutating return does NOT affect state."""
    return dict(_fallback_counter)


def reset_fallback_counters() -> None:
    """Reset counters (typically at the start of a task / pipeline run)."""
    for k in list(_fallback_counter.keys()):
        _fallback_counter[k] = 0


# ── Internal — single-provider chat construction ─────────────────────


def _build_chat(
    provider: str,
    kind: ChatKind,
    config: dict,
    *,
    timeout: int = 120,
) -> Any:
    """Construct a raw single-provider ChatModel.

    Reads the same config sections the legacy site-by-site code did:
    ``config["qwen"]`` / ``config["gemini"]`` with ``model``,
    ``deep_think_model``, ``api_key``, optional ``base_url``.
    """
    if provider == "qwen":
        from langchain_openai import ChatOpenAI
        qcfg = config.get("qwen", {}) or {}
        model = (
            qcfg.get("deep_think_model") if kind == "deep"
            else qcfg.get("model")
        ) or "qwen-plus"
        api_key = qcfg.get("api_key", "")
        if not api_key:
            raise RuntimeError("qwen.api_key empty")
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=qcfg.get(
                "base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            timeout=timeout,
        )
    # default → gemini
    from langchain_google_genai import ChatGoogleGenerativeAI
    gcfg = config.get("gemini", {}) or {}
    model = (
        gcfg.get("deep_think_model") if kind == "deep"
        else gcfg.get("model")
    ) or "gemini-2.5-flash"
    api_key = gcfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("gemini.api_key empty")
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        timeout=timeout,
    )


def _other_provider(p: str) -> str:
    return "qwen" if p == "gemini" else "gemini"


def _can_fallback(config: dict, target: str) -> bool:
    """Fallback target needs its api key configured AND
    ``llm.fallback_enabled`` not explicitly set to False (default on)."""
    if (config.get("llm") or {}).get("fallback_enabled", True) is False:
        return False
    target_cfg = config.get(target, {}) or {}
    return bool(target_cfg.get("api_key"))


class _RateLimitMarker(Exception):
    """Internal marker so ``with_fallbacks`` only swaps providers on
    rate-limit errors — auth/network/validation errors propagate
    normally and surface as the real failure to the user."""


# ── Public — resilient chat factory ─────────────────────────────────


def build_resilient_chat(
    config: dict,
    *,
    kind: ChatKind = "quick",
    user_id: int | None = None,
    timeout: int = 120,
) -> Any:
    """Build a chat client that falls back to the other provider on
    rate-limit errors.

    Returns a LangChain Runnable supporting ``.invoke(messages)`` and
    ``.with_structured_output(Schema)``. If fallback is disabled or the
    secondary provider has no key, returns the bare primary chat
    (no regression vs. pre-fallback behaviour).

    The primary is selected by :func:`get_active_provider` so env /
    user-settings / config priority is preserved unchanged. We add no
    state and never persist a provider switch — every call to this
    factory rebuilds the wrapper.
    """
    primary = get_active_provider(config, user_id=user_id)
    primary_chat = _build_chat(primary, kind, config, timeout=timeout)

    secondary = _other_provider(primary)
    if not _can_fallback(config, secondary):
        # Single-provider deployment, or fallback explicitly disabled.
        # Returning the bare primary preserves type identity for callers
        # that introspect (legacy paths that ``isinstance(chat, ChatOpenAI)``).
        return primary_chat

    secondary_chat = _build_chat(secondary, kind, config, timeout=timeout)

    from langchain_core.runnables import RunnableLambda

    def _wrap_primary(input_data):
        try:
            return primary_chat.invoke(input_data)
        except BaseException as e:  # noqa: BLE001
            if is_rate_limit_error(e):
                # Re-raise as our marker so with_fallbacks only catches
                # rate-limit signals (everything else propagates so the
                # real bug is visible).
                raise _RateLimitMarker(str(e)) from e
            raise

    def _bump_and_invoke(input_data):
        # Telemetry: a successful or attempted secondary call counts
        # as a fallback event. Bump before invoking so a subsequent
        # secondary failure (e.g. both providers down) still leaves
        # the counter incremented for operator visibility.
        _fallback_counter[f"{primary}→{secondary}"] += 1
        logger.warning(
            "LLM fallback triggered: %s rate-limited, switching to %s",
            primary, secondary,
        )
        return secondary_chat.invoke(input_data)

    counted_secondary = RunnableLambda(_bump_and_invoke)
    wrapped = RunnableLambda(_wrap_primary).with_fallbacks(
        [counted_secondary],
        exceptions_to_handle=(_RateLimitMarker,),
    )

    # Sanity-check the LangChain version: ``with_structured_output`` on
    # ``RunnableWithFallbacks`` landed in 0.3. Failing fast here beats
    # a confusing error inside ``RenderingExtractor`` later.
    if not hasattr(wrapped, "with_structured_output"):
        raise RuntimeError(
            "RunnableWithFallbacks lacks with_structured_output — "
            "LangChain version too old; pin >=0.3."
        )
    return wrapped
