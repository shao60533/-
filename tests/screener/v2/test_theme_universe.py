"""Theme detection + on-theme fallback + off-theme blacklist filtering.

Locks in the v1.22 contract: a query like "存储龙头股" must NEVER produce
BRK-B / JPM / V / MA / UNH / WMT / PG even when the LLM returns garbage,
times out, or falls all the way through to the safety net."""

from __future__ import annotations

import pytest

from stock_trading_system.screener.v2.theme_universe import (
    broad_market_blacklist,
    detect_theme,
    filter_off_theme,
    theme_fallback_universe,
)


# ── detect_theme ────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "存储龙头股",
    "存储芯片龙一",
    "美股内存板块",
    "DRAM 龙头",
    "NAND 闪存领军",
    "SSD 制造商",
    "硬盘龙头",
    "数据存储硬件",
    "memory chip leaders",
])
def test_storage_queries_match_memory_theme(q):
    theme = detect_theme(query=q)
    assert theme is not None, f"expected theme for {q!r}"
    assert theme.key == "memory_storage"


@pytest.mark.parametrize("q", [
    "美股大盘蓝筹",
    "金融股龙头",
    "高股息消费股",
    "电动车产业链",  # different theme — not registered yet, must NOT match memory
    "",
    None,
])
def test_unrelated_queries_do_not_match(q):
    assert detect_theme(query=q) is None


def test_theme_detection_uses_intent_summary():
    """LLM may strip Chinese keyword from raw query but echo it in
    intent_summary — detection must still fire."""
    theme = detect_theme(query="leader stocks", intent_summary="存储龙头")
    assert theme is not None
    assert theme.key == "memory_storage"


def test_theme_detection_uses_themes_field():
    theme = detect_theme(query="something", themes=["Memory Semiconductors"])
    assert theme is not None
    assert theme.key == "memory_storage"


# ── theme_fallback_universe ────────────────────────────────────────────

def test_storage_fallback_includes_required_pure_play_tickers():
    theme = detect_theme(query="存储龙头股")
    universe = theme_fallback_universe(theme, query="存储龙头股")
    # Hard requirement from spec.
    for required in ("MU", "WDC", "STX", "SNDK"):
        assert required in universe, f"{required} missing from storage fallback"
    # Allowed extended semis.
    assert any(t in universe for t in ("MRVL", "AVGO", "INTC", "AMD", "NVDA"))


def test_storage_fallback_excludes_cloud_when_no_explicit_keyword():
    """Plain 存储 query must NOT pull in AMZN/MSFT/GOOGL."""
    theme = detect_theme(query="存储龙头股")
    universe = theme_fallback_universe(theme, query="存储龙头股")
    for cloud in ("AMZN", "MSFT", "GOOGL"):
        assert cloud not in universe, f"{cloud} leaked into plain 存储 fallback"


@pytest.mark.parametrize("query,expected_extras", [
    ("云存储龙头", {"AMZN", "MSFT", "GOOGL"}),
    ("对象存储 leader", {"AMZN", "MSFT", "GOOGL"}),
    ("S3 存储龙头", {"AMZN"}),
    ("Azure Storage 龙头", {"MSFT"}),
])
def test_storage_fallback_includes_cloud_when_explicit(query, expected_extras):
    theme = detect_theme(query=query)
    universe = theme_fallback_universe(theme, query=query)
    for t in expected_extras:
        assert t in universe, f"{t} missing for explicit query {query!r}"


def test_storage_fallback_never_includes_broad_market_anchors():
    """No matter the query variant, BRK-B / JPM / V / MA / UNH / WMT / PG
    must never appear in the storage fallback universe."""
    theme = detect_theme(query="存储龙头股")
    for q in ("存储龙头", "云存储龙头", "DRAM 龙一", "SSD 领军"):
        universe = theme_fallback_universe(theme, query=q)
        for polluter in ("BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG"):
            assert polluter not in universe, (
                f"{polluter} leaked into storage fallback for {q!r}"
            )


# ── filter_off_theme ────────────────────────────────────────────────────

def test_filter_off_theme_drops_blacklisted_tickers_inside_theme():
    theme = detect_theme(query="存储龙头股")
    llm_output = ["MU", "BRK-B", "WDC", "JPM", "STX", "V", "MA", "UNH", "SNDK"]
    cleaned = filter_off_theme(llm_output, theme, query="存储龙头股")
    assert cleaned == ["MU", "WDC", "STX", "SNDK"]


def test_filter_off_theme_passes_through_offtheme_queries():
    """Generic queries (no theme) keep BRK-B / JPM / V — those are
    legitimate large-cap picks for "美股龙头" style asks."""
    llm_output = ["AAPL", "BRK-B", "JPM", "V"]
    cleaned = filter_off_theme(llm_output, theme=None, query="美股大盘龙头")
    assert cleaned == ["AAPL", "BRK-B", "JPM", "V"]


def test_filter_off_theme_normalizes_to_uppercase():
    theme = detect_theme(query="存储龙头股")
    cleaned = filter_off_theme(
        [" mu ", "wdc", "Stx"], theme, query="存储龙头股",
    )
    assert cleaned == ["MU", "WDC", "STX"]


def test_filter_off_theme_keeps_explicit_extras_under_cloud_query():
    """Under '云存储' the AMZN/MSFT/GOOGL extras are on-theme by
    explicit gate — even if those tickers happened to be on the broad
    blacklist, they would still pass for that query."""
    theme = detect_theme(query="云存储龙头股")
    cleaned = filter_off_theme(
        ["MU", "AMZN", "MSFT", "GOOGL", "BRK-B"], theme,
        query="云存储龙头股",
    )
    assert "AMZN" in cleaned
    assert "MSFT" in cleaned
    assert "GOOGL" in cleaned
    assert "BRK-B" not in cleaned


# ── invariant: broad_market_blacklist contract ─────────────────────────

@pytest.mark.parametrize("ticker", [
    "BRK-B", "JPM", "V", "MA", "UNH", "WMT", "PG",
])
def test_broad_market_blacklist_covers_required_polluters(ticker):
    assert ticker in broad_market_blacklist()
