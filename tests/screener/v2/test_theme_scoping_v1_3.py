"""v1.3 acceptance — theme scoping must keep broad-market polluters
out of the candidate pool no matter which path the universe filter
takes (LLM ok, LLM fails, NL parse fails, theme registry short).

Acceptance queries from the v1.3 spec — all four MUST NOT pull in any
of the mega-cap broad-market anchors that v1.0 was leaking:

* 电力能源股
* 电力股龙头
* 能源股龙头
* 新能源龙头

The forbidden polluter list is kept narrow on purpose — anchors that
v1.0 leaked into themed queries via ``_DEFAULT_US`` (BRK-B/AAPL/MSFT/V/
JPM/META/AMZN). Tickets like NVDA/AVGO are NOT polluters for power
themes because they're legitimate tech members in some sub-themes; the
gate uses per-theme blacklists, not a single global one.
"""

from __future__ import annotations

import pytest

from stock_trading_system.screener.v2 import theme_universe as tu
from stock_trading_system.screener.v2.universe import UniverseFilter
from stock_trading_system.screener.v2.nl_parser import FilterSpec
from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline


_FORBIDDEN = ("BRK-B", "BRK.B", "BRKB", "AAPL", "MSFT", "V", "JPM", "META", "AMZN")


# ── Theme detection — every acceptance query must route correctly ────


@pytest.mark.parametrize("query, expected", [
    ("电力能源股", "power_utilities"),
    ("电力股龙头", "power_utilities"),
    ("能源股龙头", "traditional_energy"),
    ("新能源龙头",   "clean_energy"),
    ("存储龙头股",   "memory_storage"),
    ("云存储龙头",   "memory_storage"),
    ("电网龙头",     "grid_electrification"),
])
def test_acceptance_query_routes_to_expected_theme(query, expected):
    theme = tu.detect_theme(query=query)
    assert theme is not None, f"{query} → no theme matched (regression)"
    assert theme.key == expected, (
        f"{query} → expected {expected}, got {theme.key}"
    )


# ── filter_off_theme drops broad-market polluters under each strong theme ──


@pytest.mark.parametrize("theme_key", [
    "power_utilities", "traditional_energy",
    "clean_energy", "grid_electrification",
])
def test_filter_off_theme_strips_forbidden_polluters(theme_key):
    """If the LLM hallucinates AAPL/MSFT/BRK-B into a power-utility
    response, ``filter_off_theme`` must drop them. Curated on-theme
    tickers stay.

    Note: ``memory_storage`` is intentionally excluded — its cloud
    sub-theme uses ``extra_when_explicit`` to whitelist MSFT/AMZN when
    the user types '云存储', so the per-theme blacklist is more
    permissive than the v1.3 power/energy themes.
    """
    theme = next(t for t in tu._THEMES if t.key == theme_key)
    polluted = list(theme.universe[:3]) + list(_FORBIDDEN)
    cleaned = tu.filter_off_theme(polluted, theme)
    for forbidden in _FORBIDDEN:
        # XOM is on-theme for traditional_energy via theme.universe so
        # it's fine to allow it through; ditto NEE for power/clean. The
        # forbidden list above only contains genuine off-theme anchors.
        if forbidden in theme.universe:
            continue
        assert forbidden not in cleaned, (
            f"{theme_key}: {forbidden} leaked through filter_off_theme: {cleaned}"
        )
    # Curated members survive the filter.
    for member in theme.universe[:3]:
        assert member in cleaned, (
            f"{theme_key}: {member} dropped from its own universe: {cleaned}"
        )


# ── UniverseFilter end-to-end (LLM unavailable path) ─────────────────


@pytest.mark.parametrize("query, theme_key", [
    ("电力能源股", "power_utilities"),
    ("电力股龙头", "power_utilities"),
    ("能源股龙头", "traditional_energy"),
    ("新能源龙头", "clean_energy"),
])
def test_universe_filter_no_llm_returns_on_theme_only(query, theme_key):
    """Layer A (LLM) is bypassed in tests because no provider is
    configured. Layer B (theme registry) must take over and yield only
    on-theme tickers — zero broad-market polluters."""
    spec = FilterSpec(
        market="us",
        themes=[theme_key],
        raw_query=query,
        target_count=20,
    )
    uf = UniverseFilter(config={})
    tickers, source = uf.filter_by_spec(spec, max_universe=20)
    assert tickers, f"{query} produced empty universe (regression)"
    # Strong theme must NEVER fall to ``default`` — that's the v1.0 bug.
    assert source != "default", (
        f"{query} fell to default universe: {tickers}"
    )
    for forbidden in _FORBIDDEN:
        assert forbidden not in tickers, (
            f"{query}: {forbidden} leaked into universe ({source}): {tickers}"
        )


# ── Pipeline candidate gate drops off-theme even if upstream slipped ──


def test_theme_fit_gate_drops_off_theme_when_strong():
    """Even if the upstream universe layer somehow let AAPL/JPM through
    (via LLM hallucination + non-standard ticker the blacklist doesn't
    know), the candidate-level gate uses fundamentals.sector to drop
    them before guru scoring."""
    pipe = ScreenerV3Pipeline(config={}, user_id=None)

    candidates = ["NEE", "SO", "DUK", "AAPL", "JPM"]
    bundles = {
        "NEE":  {"fundamentals_current": {"sector": "Utilities"}},
        "SO":   {"fundamentals_current": {"sector": "Utilities"}},
        "DUK":  {"fundamentals_current": {"sector": "Utilities"}},
        "AAPL": {"fundamentals_current": {"sector": "Technology"}},
        "JPM":  {"fundamentals_current": {"sector": "Financial Services"}},
    }
    kept, gate, meta = pipe._apply_theme_fit_gate(
        candidates, bundles,
        filter_spec={"themes": ["power_utilities"], "raw_query": "电力股龙头"},
        nl_query="电力股龙头",
    )
    assert kept == ["NEE", "SO", "DUK"]
    assert gate["parsed_theme"] == "power_utilities"
    assert gate["on_theme_count"] == 3
    # v1.4: excluded items carry {ticker, sector, reason} so the UI
    # can show *why* a name was dropped instead of just listing it.
    excluded_tickers = sorted(e["ticker"] for e in gate["excluded_off_theme"])
    assert excluded_tickers == ["AAPL", "JPM"]
    for item in gate["excluded_off_theme"]:
        assert item["sector"], f"missing sector reason: {item}"
        assert "power_utilities" in item["reason"]
    assert meta and meta["key"] == "power_utilities"


def test_theme_fit_gate_passes_through_when_off_theme():
    """Off-theme queries (e.g. plain '美股大盘') must NOT have any
    candidate dropped — the gate is a strong-theme-only safety net."""
    pipe = ScreenerV3Pipeline(config={}, user_id=None)
    candidates = ["AAPL", "MSFT", "JPM", "BRK-B"]
    kept, gate, meta = pipe._apply_theme_fit_gate(
        candidates, bundles={},
        filter_spec={}, nl_query="美股大盘",
    )
    assert kept == candidates
    assert gate["excluded_off_theme"] == []
    assert gate["parsed_theme"] is None
    assert meta is None


def test_theme_fit_gate_fails_closed_on_missing_sector_under_strong_theme():
    """v1.5 — strong-theme queries must NOT keep candidates whose
    sector is missing. The previous permissive behaviour resurrected
    LLM-hallucinated names every time the DataRouter dropped a sector
    field; under "电力股龙头" that meant IBM/ORCL/TSLA routinely got
    14 guru LLM calls each and polluted the result list.

    Curated-universe membership wins over the missing-sector rule
    (NEE / AEP / DUK are first-class members of ``power_utilities``;
    the gate accepts them even with a blank sector because the
    registry is the source of truth, not the upstream provider).
    """
    pipe = ScreenerV3Pipeline(config={}, user_id=None)
    # NEE is in the curated universe; IBM/ORCL/TSLA are not, so the
    # missing-sector branch fires for them and they must be excluded.
    candidates = ["NEE", "IBM", "ORCL", "TSLA"]
    bundles = {
        "NEE":  {"fundamentals_current": {}},          # in universe → kept
        "IBM":  {"fundamentals_current": {}},          # missing sector → excluded
        "ORCL": {"fundamentals_current": {"sector": ""}},  # blank sector → excluded
        "TSLA": {"fundamentals_current": None},        # bundle exists but no fund → excluded
    }
    kept, gate, _ = pipe._apply_theme_fit_gate(
        candidates, bundles,
        filter_spec={"themes": ["power_utilities"]},
        nl_query="电力股龙头",
    )
    assert kept == ["NEE"], (
        f"Strong-theme gate must fail-closed on missing sector; got "
        f"kept={kept}"
    )
    excluded_tickers = sorted(e["ticker"] for e in gate["excluded_off_theme"])
    assert excluded_tickers == ["IBM", "ORCL", "TSLA"]
    # Every excluded item must carry the canonical reason string so
    # the UI can group "因数据缺失被剔除" separately from "sector
    # mismatch" rejections.
    for item in gate["excluded_off_theme"]:
        assert "missing sector under strong theme" in item["reason"], (
            f"reason for {item['ticker']} should call out missing sector: {item}"
        )
        assert item["sector"] == ""


def test_theme_fit_gate_universe_member_kept_even_with_missing_sector():
    """Guard against the regression of throwing out a curated universe
    member because the provider hiccup'd on its sector. The registry
    is authoritative; ``in theme.universe`` short-circuits the
    sector check."""
    pipe = ScreenerV3Pipeline(config={}, user_id=None)
    candidates = ["NEE", "DUK", "AEP"]
    bundles = {
        "NEE": {"fundamentals_current": {}},
        "DUK": {"fundamentals_current": {"sector": ""}},
        "AEP": {"fundamentals_current": None},
    }
    kept, gate, _ = pipe._apply_theme_fit_gate(
        candidates, bundles,
        filter_spec={"themes": ["power_utilities"]},
        nl_query="电力股龙头",
    )
    assert kept == ["NEE", "DUK", "AEP"]
    assert gate["excluded_off_theme"] == []


def test_theme_fit_gate_explicit_extras_pass_through():
    """``extra_when_explicit`` triggers must let the LLM-mentioned
    extras (AMZN/MSFT/GOOGL for cloud-storage queries) through the
    gate even when their sector is Technology — the registry says
    they're on-theme for that specific query keyword.
    """
    pipe = ScreenerV3Pipeline(config={}, user_id=None)
    candidates = ["MU", "AMZN", "AAPL"]
    bundles = {
        "MU":   {"fundamentals_current": {"sector": "Semiconductors"}},
        "AMZN": {"fundamentals_current": {"sector": "Communication Services"}},
        "AAPL": {"fundamentals_current": {"sector": "Technology"}},
    }
    kept, gate, _ = pipe._apply_theme_fit_gate(
        candidates, bundles,
        filter_spec={"themes": ["memory_storage"]},
        nl_query="云存储龙头",  # triggers AMZN/MSFT/GOOGL extras
    )
    assert "AMZN" in kept, "explicit-extras trigger must pass AMZN"
    assert "MU" in kept       # curated universe member
    assert "AAPL" not in kept  # not on theme


# ── Sanity: every strong theme has on-theme members + ≥1 sector ──────


def test_every_strong_theme_has_universe_and_sectors():
    """Catches drift if someone refactors the registry and accidentally
    leaves a strong theme without a fallback universe — that would put
    Layer B back into default-mode and pollute all themed queries."""
    for theme in tu._THEMES:
        if not theme.is_strong:
            continue
        assert theme.universe, f"{theme.key} has empty fallback universe"
        assert theme.sectors, f"{theme.key} has no sectors (gate would no-op)"
