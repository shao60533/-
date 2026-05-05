"""LLMTextClient — minimal text-in / text-out abstraction for screener internals.

NOT for TradingAgents — that uses its own LangChain-based graph.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

from stock_trading_system.llm.router import get_active_provider
from stock_trading_system.utils import get_logger

logger = get_logger("llm.client")


class LLMTextClient(Protocol):
    """Minimal text-in / text-out LLM interface."""

    provider_name: str

    def chat(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
        timeout: int = 60,
    ) -> str: ...


class QwenTextClient:
    """Qwen implementation via OpenAI-compatible DashScope endpoint."""

    provider_name = "qwen"

    def __init__(self, config: dict) -> None:
        from openai import OpenAI

        qwen_cfg = config.get("qwen") or {}
        api_key = qwen_cfg.get("api_key", "")
        if not api_key:
            raise RuntimeError("Qwen selected but qwen.api_key is empty")
        base_url = qwen_cfg.get(
            "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self._model = qwen_cfg.get("model", "qwen-plus")
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self, *, system: str, user: str, json_mode: bool = False, timeout: int = 60
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "timeout": timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class GeminiTextClient:
    """Gemini implementation via google-generativeai."""

    provider_name = "gemini"

    def __init__(self, config: dict) -> None:
        api_key = (config.get("gemini") or {}).get("api_key", "")
        if not api_key:
            raise RuntimeError("Gemini selected but gemini.api_key is missing")

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model_name = (config.get("gemini") or {}).get("model", "gemini-2.5-flash")
        self._model = genai.GenerativeModel(model_name)

    def chat(
        self, *, system: str, user: str, json_mode: bool = False, timeout: int = 60
    ) -> str:
        from google.generativeai.types import GenerationConfig

        gen_cfg = GenerationConfig(
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        resp = self._model.generate_content(
            [{"role": "user", "parts": [f"{system}\n\n{user}"]}],
            generation_config=gen_cfg,
            request_options={"timeout": timeout},
        )
        return resp.text or ""


class OpenRouterTextClient:
    """OpenRouter aggregator — OpenAI-compatible chat completions.

    Defaults to the active *quick* preset for screener-internal text
    tasks (NL parsing, materialize_universe, etc). The 14-guru deep
    path uses a separate ``ChatOpenAI`` constructed in
    ``BaseGuruAgent._get_chat_model`` with role='deep' and tool calling
    enabled — both share the same preset registry via
    ``resolve_openrouter_model``.

    Why quick by default: this client carries *cheap* internal prompts
    (criteria → tickers, NL → FilterSpec) that don't need Pro-tier
    reasoning. The Pro tier costs more and is reserved for the
    14-guru analysis loop where the extra reasoning depth pays off.

    OR-specific extras:
    - ``HTTP-Referer`` / ``X-Title`` headers for analytics on the OR
      dashboard (optional, defaults to the StockAI Terminal title).
    - ``provider_order`` in extra_body when the active preset declares
      one — lets us prefer e.g. DeepSeek's first-party endpoint and
      fall back to Novita / Fireworks when first-party throttles.
    """

    provider_name = "openrouter"

    def __init__(self, config: dict) -> None:
        from openai import OpenAI
        from stock_trading_system.llm.router import resolve_openrouter_model

        or_cfg = config.get("openrouter") or {}
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or or_cfg.get("api_key", "")
        )
        if not api_key:
            raise RuntimeError(
                "OpenRouter selected but openrouter.api_key is empty "
                "(and no OPENROUTER_API_KEY env)"
            )

        # Quick preset by default — see class docstring. Falls through
        # to the hardcoded safe default if presets registry is empty.
        preset = resolve_openrouter_model(config, role="quick")
        self._model = preset["model"] or "deepseek/deepseek-v4-flash"
        self._provider_order = preset.get("provider_order") or []

        default_headers: dict = {}
        if or_cfg.get("http_referer"):
            default_headers["HTTP-Referer"] = or_cfg["http_referer"]
        if or_cfg.get("x_title"):
            default_headers["X-Title"] = or_cfg["x_title"]

        self._client = OpenAI(
            api_key=api_key,
            base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
            default_headers=default_headers or None,
        )

    def chat(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = False,
        timeout: int = 60,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "timeout": timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._provider_order:
            # OR-specific routing hint. ``allow_fallbacks: True`` lets
            # OR walk the order list when the first vendor throttles
            # rather than failing the call outright.
            kwargs["extra_body"] = {
                "provider": {
                    "order": self._provider_order,
                    "allow_fallbacks": True,
                },
            }
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def get_text_client(config: dict) -> LLMTextClient:
    """Factory. Returns the client for the currently active provider."""
    provider = get_active_provider(config)
    if provider == "qwen":
        return QwenTextClient(config)
    if provider == "openrouter":
        return OpenRouterTextClient(config)
    return GeminiTextClient(config)
