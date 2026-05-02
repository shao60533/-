"""End-to-end on UniverseFilter: when the user types 存储龙头股 the
returned tickers must be on-theme regardless of whether the LLM is
available, throws, or returns padded broad-market mega-caps."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.screener.v2.nl_parser import FilterSpec
from stock_trading_system.screener.v2.universe import UniverseFilter


_BROAD_POLLUTERS = ("BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG")


def _spec_storage(target=20) -> FilterSpec:
    """FilterSpec the way NLParser would emit it for 存储龙头股."""
    return FilterSpec(
        intent_summary="存储芯片龙头",
        market="us",
        sectors=["Semiconductors"],
        themes=["Memory Semiconductors", "Data Storage Hardware"],
        target_count=target,
        natural_fallback=["存储", "DRAM", "NAND"],
        raw_query="存储龙头股",
    )


def _cfg():
    return {
        "llm_provider": "qwen",
        "qwen": {"api_key": "sk-test", "model": "qwen-plus"},
    }


# ── LLM unavailable → theme fallback (NOT _DEFAULT_US) ─────────────────

def test_storage_query_with_no_llm_returns_theme_universe():
    """If both LLM and QwenProvider are down, Layer C must use the
    on-theme fallback, not the broad-market _DEFAULT_US list."""
    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(_cfg())
        tickers, source = uf.filter_by_spec(_spec_storage(), max_universe=20)

    # Hard-requirement core picks present.
    for required in ("MU", "WDC", "STX", "SNDK"):
        assert required in tickers, f"{required} missing in {tickers}"
    # Broad-market polluters absent.
    for polluter in _BROAD_POLLUTERS:
        assert polluter not in tickers, f"{polluter} leaked into {tickers}"
    assert source == "theme_fallback"


# ── LLM returns garbage that includes polluters → blacklist filter ─────

def test_storage_query_filters_broad_market_pollution_from_llm_output():
    """An LLM that pads its answer with BRK-B/JPM/V must be filtered
    before scoring."""
    mock_client = MagicMock(provider_name="qwen")
    mock_client.chat.return_value = json.dumps({
        # Realistic shape of the bad output the user reported, plus
        # genuine on-theme picks.
        "tickers": [
            "AMZN", "AAPL", "BRK-B", "JPM", "V", "META", "GOOGL", "MSFT",
            "MU", "WDC", "STX",
        ],
    })
    with patch("stock_trading_system.llm.client.get_text_client",
               return_value=mock_client), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(_cfg())
        tickers, source = uf.filter_by_spec(_spec_storage(), max_universe=20)

    for polluter in _BROAD_POLLUTERS:
        assert polluter not in tickers, f"{polluter} leaked: {tickers}"
    # Plain 存储 query (NO 云存储) → AMZN/MSFT/GOOGL are not theme-extras
    # and are not on the blacklist either, so they pass through. The
    # important contract is that the BROAD polluters are gone.
    assert "MU" in tickers
    assert "WDC" in tickers
    assert source == "llm"


# ── Cloud-storage carve-out: AMZN/MSFT/GOOGL allowed when explicit ────

def test_cloud_storage_query_allows_hyperscalers():
    """When the user explicitly types '云存储' the prompt + extras open
    AMZN/MSFT/GOOGL as on-theme. The broad polluters stay blocked."""
    spec = _spec_storage()
    spec.raw_query = "云存储龙头股"

    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(_cfg())
        tickers, source = uf.filter_by_spec(spec, max_universe=20)

    assert "AMZN" in tickers
    assert "MSFT" in tickers
    assert "GOOGL" in tickers
    for polluter in _BROAD_POLLUTERS:
        assert polluter not in tickers
    assert source == "theme_fallback"


# ── Off-theme query keeps the legacy _DEFAULT_US fallback path ─────────

def test_offtheme_query_still_uses_default_us_fallback():
    """Generic '美股大盘龙头' is allowed to pull from _DEFAULT_US (which
    legitimately includes BRK-B/JPM/V) — the new theme guard MUST NOT
    leak into off-theme runs."""
    spec = FilterSpec(
        intent_summary="美股大盘龙头",
        market="us",
        target_count=10,
        raw_query="美股大盘龙头",
    )
    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(_cfg())
        tickers, source = uf.filter_by_spec(spec, max_universe=10)

    # Regression guard: off-theme path is unchanged.
    assert source in ("heuristic", "default")
    # Some classic mega-cap appears (don't pin to specific ticker — list
    # ordering is implementation detail).
    assert tickers
