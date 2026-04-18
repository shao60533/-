"""TC-MS-U13 ~ U16: LLMTextClient factory unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.llm.client import (
    GeminiTextClient,
    QwenTextClient,
    get_text_client,
)


# ── TC-MS-U13: active=qwen → QwenTextClient ──────────────────────


def test_factory_returns_qwen(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"qwen": {"api_key": "k"}}
    with patch("stock_trading_system.llm.client.QwenTextClient") as mock_cls:
        mock_cls.return_value = MagicMock(provider_name="qwen")
        client = get_text_client(cfg)
        assert client.provider_name == "qwen"


# ── TC-MS-U14: active=gemini → GeminiTextClient (mocked) ─────────


def test_factory_returns_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = {"llm_provider": "gemini", "gemini": {"api_key": "g"}}
    with patch("stock_trading_system.llm.client.GeminiTextClient") as mock_cls:
        mock_cls.return_value = MagicMock(provider_name="gemini")
        client = get_text_client(cfg)
        assert client.provider_name == "gemini"


# ── TC-MS-U15: Gemini client missing key → raise ─────────────────


def test_gemini_client_missing_key_raises():
    with pytest.raises(RuntimeError, match="api_key is missing"):
        GeminiTextClient({"gemini": {}})


def test_qwen_client_missing_key_raises():
    with pytest.raises(RuntimeError, match="api_key is empty"):
        QwenTextClient({"qwen": {}})


# ── TC-MS-U16: json_mode both clients (mock response) ────────────


def test_qwen_json_mode():
    """QwenTextClient passes response_format when json_mode=True."""
    with patch("openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"result": 42}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai.return_value = mock_client

        client = QwenTextClient({"qwen": {"api_key": "k"}})
        result = client.chat(system="sys", user="usr", json_mode=True)
        assert result == '{"result": 42}'

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}


def test_gemini_json_mode():
    """GeminiTextClient sets response_mime_type when json_mode=True."""
    import sys

    mock_genai = MagicMock()
    mock_types = MagicMock()
    mock_model = MagicMock()
    mock_resp = MagicMock(text='{"items": []}')
    mock_model.generate_content.return_value = mock_resp
    mock_genai.GenerativeModel.return_value = mock_model

    google_mock = MagicMock()
    google_mock.generativeai = mock_genai

    with patch.dict(sys.modules, {
        "google": google_mock,
        "google.generativeai": mock_genai,
        "google.generativeai.types": mock_types,
    }):
        client = GeminiTextClient({"gemini": {"api_key": "AIza"}})
        result = client.chat(system="sys", user="usr", json_mode=True)
        assert result == '{"items": []}'
