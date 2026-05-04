"""TC-MS-I7 ~ I11: Screener V2 provider switching integration tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.screener.v2.nl_parser import NLParser, FilterSpec
from stock_trading_system.screener.v2.universe import UniverseFilter


def _cfg(provider="qwen"):
    return {
        "llm_provider": provider,
        "qwen": {"api_key": "sk-test", "model": "qwen-plus",
                 "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "gemini": {"api_key": "AIza-test", "model": "gemini-2.5-flash"},
    }


# ── TC-MS-I7: NL parser with Qwen client ─────────────────────────


def test_nl_parser_qwen(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _cfg("qwen")
    mock_client = MagicMock(provider_name="qwen")
    mock_client.chat.return_value = json.dumps({
        "intent_summary": "科技股低估",
        "market": "us",
        "sectors": ["Technology"],
        "themes": ["AI"],
        "criteria": {"max_pe": 30},
        "target_count": 20,
        "natural_fallback": ["科技股", "低估"],
    })

    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_client):
        parser = NLParser(cfg)
        spec = parser.parse("科技股 PE<30")

    assert spec.market == "us"
    assert "Technology" in spec.sectors
    assert spec.criteria.get("max_pe") == 30


# ── TC-MS-I8: NL parser with Gemini client ───────────────────────


def test_nl_parser_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _cfg("gemini")
    mock_client = MagicMock(provider_name="gemini")
    mock_client.chat.return_value = json.dumps({
        "intent_summary": "tech stocks undervalued",
        "market": "us",
        "sectors": ["Technology"],
        "themes": [],
        "criteria": {"max_pe": 30},
        "target_count": 30,
        "natural_fallback": ["tech", "undervalued"],
    })

    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_client):
        parser = NLParser(cfg)
        spec = parser.parse("科技股 PE<30")

    assert spec.market == "us"
    assert spec.criteria.get("max_pe") == 30


# ── TC-MS-I9: Universe filter runs with both providers ───────────


def test_universe_llm_call(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _cfg("qwen")
    mock_client = MagicMock(provider_name="qwen")
    mock_client.chat.return_value = json.dumps({
        "tickers": ["AAPL", "MSFT", "GOOGL", "NVDA", "AMD"],
    })

    spec = FilterSpec(
        market="us",
        sectors=["Technology"],
        target_count=10,
    )

    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_client):
        # Also mock QwenProvider to be unavailable so it hits the LLM fallback
        with patch("stock_trading_system.screener.v2.universe.UniverseFilter._get_qwen", return_value=None):
            uf = UniverseFilter(cfg)
            tickers, source = uf.filter_by_spec(spec)

    assert len(tickers) >= 1
    assert source == "dynamic_llm"
    assert "AAPL" in tickers


# ── TC-MS-I10: NL parser LLM failure → fallback to keyword ───────


def test_nl_parser_fallback_on_failure(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _cfg("qwen")
    mock_client = MagicMock(provider_name="qwen")
    mock_client.chat.side_effect = RuntimeError("LLM down")

    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_client):
        parser = NLParser(cfg)
        spec = parser.parse("AI 成长股")

    # Should degrade gracefully to keyword fallback
    assert "AI 成长股" in spec.raw_query or "AI 成长股" in spec.natural_fallback
    assert "LLM 不可用" in spec.intent_summary or len(spec.natural_fallback) > 0


# ── TC-MS-I11: Switch provider mid-session → universe uses new ───


def test_universe_switch_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    cfg = _cfg("qwen")

    mock_qwen_client = MagicMock(provider_name="qwen")
    mock_qwen_client.chat.return_value = json.dumps({"tickers": ["BABA", "JD"]})

    mock_gemini_client = MagicMock(provider_name="gemini")
    mock_gemini_client.chat.return_value = json.dumps({"tickers": ["GOOGL", "META"]})

    spec = FilterSpec(market="us", target_count=5)

    # First call with Qwen
    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_qwen_client):
        with patch("stock_trading_system.screener.v2.universe.UniverseFilter._get_qwen", return_value=None):
            uf = UniverseFilter(cfg)
            t1, s1 = uf.filter_by_spec(spec)

    assert "BABA" in t1

    # Switch to Gemini — create new instance (simulates real switch)
    cfg2 = _cfg("gemini")
    with patch("stock_trading_system.llm.client.get_text_client", return_value=mock_gemini_client):
        with patch("stock_trading_system.screener.v2.universe.UniverseFilter._get_qwen", return_value=None):
            uf2 = UniverseFilter(cfg2)
            t2, s2 = uf2.filter_by_spec(spec)

    assert "GOOGL" in t2
