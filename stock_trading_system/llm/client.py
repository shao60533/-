"""LLMTextClient — minimal text-in / text-out abstraction for screener internals.

NOT for TradingAgents — that uses its own LangChain-based graph.
"""

from __future__ import annotations

import json
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
        # 2026-05-04: source-level default tracks the YAML default
        # (``qwen3.6-max-preview``). Fires only when the runtime config
        # has no explicit ``qwen.model`` — production ships a value.
        self._model = qwen_cfg.get("model", "qwen3.6-max-preview")
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


def get_text_client(config: dict) -> LLMTextClient:
    """Factory. Returns the client for the currently active provider."""
    provider = get_active_provider(config)
    if provider == "qwen":
        return QwenTextClient(config)
    return GeminiTextClient(config)
