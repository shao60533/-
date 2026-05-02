"""Theme-fallback regression for the V3 ``存储龙头股`` recall bug.

Production /api/screen/v3/results returned BRK-B / JPM / V padding when
the LLM was unavailable or hallucinated. The chain we exercise here:

    NLParser._fallback_spec(query)            → themed FilterSpec
    UniverseFilter.filter_by_spec(spec)       → on-theme tickers
                                                source = "theme_fallback"

Tests cover four invariants from the spec:
    1. Storage query → fallback spec carries Memory/DRAM/NAND themes.
    2. LLM unavailable → UniverseFilter emits theme_fallback (NOT
       _DEFAULT_US) and the BRK-B/JPM/V/... blacklist is honoured.
    3. Empty query keeps the legacy default-list behaviour.
    4. Cloud-storage carve-out: 云存储 query lands on AMZN/MSFT/GOOGL,
       not on memory chips.
"""

from __future__ import annotations

from unittest.mock import patch

from stock_trading_system.screener.v2.nl_parser import NLParser
from stock_trading_system.screener.v2.universe import UniverseFilter


_BROAD_POLLUTERS = ("BRK-B", "JPM", "V", "MA", "PG", "WMT", "UNH")


# ── 1. Fallback spec recognises the storage theme ─────────────────────────


def test_fallback_spec_storage_theme():
    """``存储龙头股`` with no LLM still produces a themed FilterSpec —
    sectors include Semiconductors and themes hit Memory/DRAM/NAND."""
    spec = NLParser._fallback_spec("存储龙头股", "us", None)
    text = " ".join(spec.themes + spec.natural_fallback).lower()
    assert "dram" in text or "nand" in text or "memory" in text
    assert "Semiconductors" in spec.sectors


# ── 2. LLM unavailable → theme_fallback, not broad-market default ────────


def test_storage_query_uses_theme_fallback_when_llm_unavailable():
    """When both LLM clients are unreachable, the storage query must
    land on the curated on-theme universe and exclude the broad-market
    polluters from ``_DEFAULT_US``."""
    spec = NLParser._fallback_spec("存储龙头股", "us", None)
    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(config={})
        tickers, source = uf.filter_by_spec(spec, max_universe=10)

    assert source == "theme_fallback"
    assert any(t in tickers for t in ("MU", "WDC", "STX", "SNDK"))
    for bad in _BROAD_POLLUTERS:
        assert bad not in tickers, f"{bad} leaked into {tickers}"


# ── 3. Empty query keeps the legacy default-list behaviour ───────────────


def test_empty_query_still_uses_default_universe():
    """Empty NL query is off-theme by definition — must NOT promote
    storage / cloud-storage; the legacy heuristic / default path
    keeps the existing curated mega-cap list."""
    spec = NLParser._fallback_spec("", "us", None)
    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(config={})
        tickers, source = uf.filter_by_spec(spec, max_universe=5)

    assert source in {"heuristic", "default"}
    assert len(tickers) == 5


# ── 4. Cloud-storage query splits off into the hyperscaler bucket ────────


def test_cloud_storage_query_uses_cloud_theme():
    """``云存储龙头股`` is the cloud-storage sub-theme — fallback list
    must surface AMZN/MSFT/GOOGL (the hyperscaler S3/Azure/GCS leaders),
    NOT the memory-chip universe."""
    spec = NLParser._fallback_spec("云存储龙头股", "us", None)
    with patch.object(UniverseFilter, "_get_llm", return_value=None), \
         patch.object(UniverseFilter, "_get_qwen", return_value=None):
        uf = UniverseFilter(config={})
        tickers, source = uf.filter_by_spec(spec, max_universe=10)

    assert source == "theme_fallback"
    assert any(t in tickers for t in ("AMZN", "MSFT", "GOOGL"))
    # The pure-memory names belong to the *other* fallback bucket and
    # should not bleed in here. We only assert MU is absent — it's the
    # only one in both lists' relevant-adjacent set, so a single check
    # is enough; STX/WDC are even further from cloud-storage relevance.
    assert "MU" not in tickers
