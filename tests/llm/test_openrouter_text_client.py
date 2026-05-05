"""OpenRouterTextClient — 5 cases per docs/design/llm-openrouter.md v1.0 §9.1.

Tests mock ``openai.OpenAI`` so we don't hit the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_response(text: str = "ok"):
    """Build the chained ``client.chat.completions.create()`` return shape."""
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def or_config_with_quick_preset():
    return {
        "openrouter": {
            "api_key": "sk-or-test",
            "base_url": "https://openrouter.ai/api/v1",
            "http_referer": "https://stockai.example.com",
            "x_title": "StockAI Terminal",
            "presets": [
                {"id": "deep-pro",   "label": "Deep Pro",
                 "model": "deepseek/deepseek-v4-pro",
                 "role": "deep",
                 "provider_order": ["deepseek"]},
                {"id": "quick-flash", "label": "Quick Flash",
                 "model": "deepseek/deepseek-v4-flash",
                 "role": "quick",
                 "provider_order": ["deepseek", "novita"]},
            ],
            "active": {"deep": "deep-pro", "quick": "quick-flash"},
        },
    }


def test_init_uses_quick_preset_model(or_config_with_quick_preset):
    """Text client defaults to the active *quick* preset, not deep."""
    from stock_trading_system.llm.client import OpenRouterTextClient

    with patch("stock_trading_system.llm.client.os") as os_mod:
        os_mod.environ = {}
        with patch("openai.OpenAI") as mock_oai:
            client = OpenRouterTextClient(or_config_with_quick_preset)
        assert client._model == "deepseek/deepseek-v4-flash"
        # provider_order propagated from the quick preset
        assert client._provider_order == ["deepseek", "novita"]
        # OpenAI was constructed with the OR base_url
        ctor_kwargs = mock_oai.call_args.kwargs
        assert ctor_kwargs["base_url"] == "https://openrouter.ai/api/v1"
        assert ctor_kwargs["api_key"] == "sk-or-test"


def test_init_raises_without_api_key(monkeypatch):
    """Empty key in yaml AND no env → constructor must raise rather
    than silently producing a broken client."""
    from stock_trading_system.llm.client import OpenRouterTextClient

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = {"openrouter": {"api_key": ""}}
    with patch("openai.OpenAI"):
        with pytest.raises(RuntimeError, match="api_key is empty"):
            OpenRouterTextClient(cfg)


def test_env_key_overrides_yaml(monkeypatch, or_config_with_quick_preset):
    """OPENROUTER_API_KEY env wins over yaml api_key — cloud contract."""
    from stock_trading_system.llm.client import OpenRouterTextClient

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")
    with patch("openai.OpenAI") as mock_oai:
        OpenRouterTextClient(or_config_with_quick_preset)
    assert mock_oai.call_args.kwargs["api_key"] == "sk-or-from-env"


def test_chat_passes_provider_order_via_extra_body(or_config_with_quick_preset, monkeypatch):
    """When the active preset declares provider_order, the chat call
    must forward it as ``extra_body.provider.order`` so OR routes to
    the preferred vendor first and falls back to the others."""
    from stock_trading_system.llm.client import OpenRouterTextClient

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response("hello")
    with patch("openai.OpenAI", return_value=mock_client):
        client = OpenRouterTextClient(or_config_with_quick_preset)
    out = client.chat(system="sys", user="usr")
    assert out == "hello"
    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["extra_body"] == {
        "provider": {
            "order": ["deepseek", "novita"],
            "allow_fallbacks": True,
        },
    }
    # json_mode default False — no response_format injected
    assert "response_format" not in create_kwargs


def test_chat_json_mode_sets_response_format(or_config_with_quick_preset, monkeypatch):
    """json_mode=True must add ``response_format={"type": "json_object"}``
    so OR's compatible providers honor structured output."""
    from stock_trading_system.llm.client import OpenRouterTextClient

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response('{"k":1}')
    with patch("openai.OpenAI", return_value=mock_client):
        client = OpenRouterTextClient(or_config_with_quick_preset)
    client.chat(system="sys", user="usr", json_mode=True)
    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["response_format"] == {"type": "json_object"}


def test_factory_returns_or_client_when_provider_is_openrouter(monkeypatch, or_config_with_quick_preset):
    """get_text_client → OpenRouterTextClient when provider routes there."""
    from stock_trading_system.llm.client import (
        OpenRouterTextClient,
        get_text_client,
    )

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    with patch("openai.OpenAI"):
        client = get_text_client(or_config_with_quick_preset)
    assert isinstance(client, OpenRouterTextClient)
    assert client.provider_name == "openrouter"
