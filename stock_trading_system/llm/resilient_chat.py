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

    Empty ``api_key`` is tolerated at construction (matches legacy
    behaviour) — it will surface as an auth error at invoke time, NOT
    at build time, so existing tests that build agents without keys
    keep working. ``_can_fallback`` separately gates whether the
    *secondary* provider participates.
    """
    if provider == "qwen":
        from langchain_openai import ChatOpenAI
        qcfg = config.get("qwen", {}) or {}
        model = (
            qcfg.get("deep_think_model") if kind == "deep"
            else qcfg.get("model")
        ) or "qwen-plus"
        return ChatOpenAI(
            model=model,
            api_key=qcfg.get("api_key", ""),
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
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=gcfg.get("api_key", ""),
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


def _wrap_pair_with_fallback(
    primary_chat: Any,
    secondary_chat: Any,
    primary_name: str,
    secondary_name: str,
) -> Any:
    """Build a ``RunnableWithFallbacks`` that swaps ``primary_chat`` for
    ``secondary_chat`` on rate-limit only.

    Used twice: once with the bare provider chats (so ``.invoke()``
    works), and again — by :class:`_ResilientChat.with_structured_output`
    — with each side already pre-wrapped via ``with_structured_output``.
    Keeping the wiring in one place avoids duplicated rate-limit
    classification logic.
    """
    from langchain_core.runnables import RunnableLambda

    def _wrap_primary(input_data):
        try:
            return primary_chat.invoke(input_data)
        except BaseException as e:  # noqa: BLE001
            if is_rate_limit_error(e):
                # Re-raise as marker so with_fallbacks only catches
                # rate-limit signals (everything else propagates so
                # the real bug is visible).
                raise _RateLimitMarker(str(e)) from e
            raise

    def _bump_and_invoke(input_data):
        # Bump before invoking so even a secondary failure (both
        # providers limited) leaves the counter incremented for
        # operator visibility.
        _fallback_counter[f"{primary_name}→{secondary_name}"] += 1
        logger.warning(
            "LLM fallback triggered: %s rate-limited, switching to %s",
            primary_name, secondary_name,
        )
        return secondary_chat.invoke(input_data)

    return RunnableLambda(_wrap_primary).with_fallbacks(
        [RunnableLambda(_bump_and_invoke)],
        exceptions_to_handle=(_RateLimitMarker,),
    )


class _ResilientChat:
    """Thin proxy that exposes ``.invoke()`` and
    ``.with_structured_output()`` on top of two provider-specific chat
    clients with rate-limit-driven fallback.

    LangChain ≥1.2 removed ``with_structured_output`` from
    ``RunnableWithFallbacks`` — the canonical fix is to apply
    ``with_structured_output(Schema)`` to each side BEFORE wrapping
    with fallbacks. This proxy does exactly that on demand.
    """

    def __init__(self, primary_chat: Any, secondary_chat: Any,
                 primary_name: str, secondary_name: str):
        self._primary = primary_chat
        self._secondary = secondary_chat
        self._primary_name = primary_name
        self._secondary_name = secondary_name
        # Eagerly build the bare ``invoke()`` runnable so callers that
        # only call ``.invoke()`` skip the lazy path.
        self._runnable = _wrap_pair_with_fallback(
            primary_chat, secondary_chat,
            primary_name, secondary_name,
        )

    def invoke(self, input_data, **kwargs):
        return self._runnable.invoke(input_data, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        """Return a new resilient runnable that yields ``schema``-shaped
        outputs from whichever provider responds.

        Both sides get ``with_structured_output(schema)`` applied
        BEFORE the fallback wrapping so each is responsible for its
        own format coercion (Gemini and Qwen disagree on JSON schema
        delivery — neither can coerce the other's output)."""
        primary_struct = self._primary.with_structured_output(schema, **kwargs)
        secondary_struct = self._secondary.with_structured_output(schema, **kwargs)
        return _wrap_pair_with_fallback(
            primary_struct, secondary_struct,
            self._primary_name, self._secondary_name,
        )


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

    Returns either a bare provider chat (single-provider deployment or
    fallback disabled) or a :class:`_ResilientChat` proxy that exposes
    ``.invoke(messages)`` and ``.with_structured_output(Schema)``. The
    proxy applies ``with_structured_output`` to each provider chat
    BEFORE the fallback wrapping — required by LangChain ≥1.2 which
    no longer surfaces ``with_structured_output`` on
    ``RunnableWithFallbacks``.

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
        # Returning the bare primary preserves type identity for
        # callers that introspect (legacy paths that
        # ``isinstance(chat, ChatOpenAI)``).
        return primary_chat

    secondary_chat = _build_chat(secondary, kind, config, timeout=timeout)
    return _ResilientChat(
        primary_chat, secondary_chat, primary, secondary,
    )
