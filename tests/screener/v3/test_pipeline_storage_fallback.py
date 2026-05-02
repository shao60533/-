"""ScreenerV3Pipeline._get_candidates exception path must use the
theme-aware fallback for storage queries — not the legacy mega-cap
list that contained BRK-B/JPM/V/MA/UNH/WMT/PG."""

from __future__ import annotations

import asyncio

import pytest

from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline


_BROAD_POLLUTERS = ("BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pipeline(monkeypatch):
    """Build a Pipeline whose v2 import raises so we exercise the
    fallback branch of ``_get_candidates`` directly."""
    pipe = ScreenerV3Pipeline(config={}, local_cache=None)
    # Force the try-block to raise: monkeypatch the v2 nl_parser import
    # path so it explodes the moment _get_candidates touches it.
    import sys
    import types
    bad = types.ModuleType("stock_trading_system.screener.v2.nl_parser")

    def _broken(*_a, **_kw):
        raise RuntimeError("simulated v2 outage")

    bad.NLParser = _broken
    monkeypatch.setitem(
        sys.modules,
        "stock_trading_system.screener.v2.nl_parser",
        bad,
    )
    yield pipe


def test_storage_query_fallback_returns_theme_universe(pipeline):
    # ``_get_candidates`` returns ``(tickers, spec, source)`` — unpack so
    # the membership checks below see the ticker list, not the 3-tuple.
    tickers, _spec, source = _run(pipeline._get_candidates("存储龙头股", "us", 20))
    assert tickers, "fallback must return SOMETHING for a themed query"
    assert source == "theme_fallback"
    for required in ("MU", "WDC", "STX", "SNDK"):
        assert required in tickers, (
            f"{required} missing from themed fallback: {tickers}"
        )
    for polluter in _BROAD_POLLUTERS:
        assert polluter not in tickers, (
            f"{polluter} leaked into themed fallback: {tickers}"
        )


def test_offtheme_fallback_uses_generic_megacap_list(pipeline):
    """Generic '美股大盘' query has no theme — fallback is allowed to
    return the trimmed mega-cap list. (Note: BRK-B/JPM/V have been
    removed from the fallback list as part of v1.22.)"""
    tickers, _spec, _source = _run(pipeline._get_candidates("美股大盘", "us", 10))
    assert tickers
    # Even off-theme, the generic mega-cap fallback no longer carries
    # the worst offenders — keeps the user's spec direction even when
    # we're not strictly themed.
    for polluter in ("BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG"):
        assert polluter not in tickers, (
            f"{polluter} found in off-theme fallback: {tickers}"
        )
