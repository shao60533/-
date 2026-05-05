"""v1.7 — structured-summary state machine classifier.

Locks the contract that drove the "无结构化数据时只折叠到调试块" fix:
``classify`` must distinguish empty-input / partial-extraction /
total-failure so the API + UI can route to the right banner state.
"""

from __future__ import annotations

from stock_trading_system.agents.rendering.status import (
    available_tabs, classify,
)


def test_classify_empty_returns_empty():
    assert classify(None) == ("empty", None)
    assert classify({}) == ("empty", None)


def test_classify_full_success():
    rendering = {
        "summary": {"rating": "Buy"}, "Market": {"trend": "bullish"},
        "Sentiment": {"mood": "greed"}, "News": {"summary": "x"},
        "Fundamentals": {"summary": "x"},
        "Investment Debate": {"verdict": "bull"},
        "Risk Assessment": {"verdict": "low"},
        "Decision": {"final_action": "BUY"},
    }
    status, err = classify(rendering)
    assert status == "success"
    assert err is None


def test_classify_partial_when_some_tabs_missing_with_source_present():
    """User-visible meaning: 8 tabs had source markdown, only 5 made
    it through the LLM. UI shows the 5 cards + markdown fallback for
    the 3 that didn't, and the API surfaces ``partial`` so the inbox
    can mark the row 'incomplete'."""
    rendering = {
        "summary": {"rating": "Buy"}, "Market": {"trend": "bullish"},
        "Sentiment": None, "News": None, "Fundamentals": {"summary": "x"},
        "Investment Debate": {"verdict": "bull"},
        "Risk Assessment": None, "Decision": {"final_action": "BUY"},
    }
    status, err = classify(rendering)
    assert status == "partial"
    assert err and "missing tabs" in err
    # No report bodies leak — only structural names.
    assert "missing tabs: " in err
    for tab in ("Sentiment", "News", "Risk Assessment"):
        assert tab in err


def test_classify_failed_when_all_extracted_none_with_sources_present():
    """LLM down / structured output validation failed for every tab."""
    rendering = {k: None for k in (
        "summary", "Market", "Sentiment", "News", "Fundamentals",
        "Investment Debate", "Risk Assessment", "Decision",
    )}
    status, err = classify(rendering)
    assert status == "failed"
    assert err and "all 8 tabs failed" in err


def test_classify_empty_when_no_source_tabs():
    """If the analyzer didn't write any source markdown (quick mode
    skips a bunch), an all-None rendering is ``empty``, not ``failed``
    — there's nothing to retry against."""
    rendering = {k: None for k in ("summary", "Market", "Decision")}
    status, err = classify(rendering, source_tabs_present=[])
    assert status == "empty"
    assert err is None


def test_available_tabs_returns_keys_with_dict_values():
    rendering = {
        "summary": {"rating": "Buy"}, "Market": None,
        "News": {"summary": "x"}, "Decision": {},
    }
    tabs = available_tabs(rendering)
    # ``{}`` is falsy → not counted; only non-empty dicts surface.
    assert tabs == ["summary", "News"]


def test_available_tabs_handles_garbage():
    assert available_tabs(None) == []
    assert available_tabs({}) == []
    assert available_tabs("not a dict") == []  # type: ignore[arg-type]
