"""hardening-iteration-v1 P2.4 [H11] — Qwen prompt themes externalised.

Pre-P2.4 the theme-to-tickers map was hard-coded inside the qwen
provider's system prompt: every roster tweak meant a code commit and
a deploy. The map now lives in ``config/themes.yaml`` and is spliced
into the prompt at runtime.

This suite locks down:
    1. config/themes.yaml ships and parses with the expected shape.
    2. _build_theme_prompt() renders the expected sub-clauses for each
       theme (cn keywords, en description, tickers list).
    3. excluded_tickers + excluded_unless_gating reach the prompt.
    4. blocklist_for_strong_themes reaches the prompt.
    5. Defensive: no theme tickers leak as Python literals back into
       qwen_provider.py (regression guard for the H11 closure).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_themes_yaml_exists_and_parses():
    """Shipping config — must be present and valid YAML."""
    from stock_trading_system.data.qwen_provider import _load_themes
    data = _load_themes.__wrapped__()  # bypass lru_cache
    assert "themes" in data
    themes = data["themes"]
    # Schema discipline: every theme has cn_keywords + tickers minimum.
    for tid, t in themes.items():
        assert "cn_keywords" in t, f"theme {tid} missing cn_keywords"
        assert "tickers" in t, f"theme {tid} missing tickers"
        assert len(t["tickers"]) > 0, f"theme {tid} has no tickers"


def test_prompt_includes_utilities_sector():
    from stock_trading_system.data.qwen_provider import _build_theme_prompt
    prompt = _build_theme_prompt()
    assert "电力" in prompt
    assert "Utilities" in prompt
    assert "NEE" in prompt and "DUK" in prompt


def test_prompt_includes_storage_with_gating():
    """Cloud-storage names should appear behind a gating-keyword clause."""
    from stock_trading_system.data.qwen_provider import _build_theme_prompt
    prompt = _build_theme_prompt()
    assert "存储" in prompt
    assert "MU" in prompt
    assert "云存储" in prompt or "对象存储" in prompt
    assert "AMZN" in prompt  # gating ticker


def test_prompt_includes_energy_oil_exclusions():
    from stock_trading_system.data.qwen_provider import _build_theme_prompt
    prompt = _build_theme_prompt()
    assert "XOM" in prompt and "CVX" in prompt
    # New-energy tickers must be excluded from plain 能源 query
    assert "NEE/FSLR/ENPH" in prompt or all(t in prompt for t in ("NEE", "FSLR", "ENPH"))


def test_prompt_blocklist_for_strong_themes_present():
    from stock_trading_system.data.qwen_provider import _build_theme_prompt
    prompt = _build_theme_prompt()
    assert "禁止" in prompt and "强主题" in prompt
    # generic large-caps blocklist
    assert "BRK-B" in prompt and "WMT" in prompt


def test_no_hardcoded_ticker_groups_in_qwen_provider():
    """P2.4 regression guard: ticker lists must live in themes.yaml,
    not be glued back into the .py file. Allow the docstring history
    reference but flag any string-literal ticker triples in code."""
    from stock_trading_system.data import qwen_provider as qp_mod
    src = Path(qp_mod.__file__).read_text(encoding="utf-8")

    # Strip the module docstring (the only legitimate place the words
    # NEE/SO/DUK can appear after P2.4 — as historical context).
    # Split on the closing triple-quote of the top docstring.
    after_doc = src.split('"""', 2)
    body = after_doc[2] if len(after_doc) >= 3 else src

    # Forbidden patterns: three or more all-caps tickers separated by
    # "/" in a string literal. This is the shape the inline lists used
    # ("NEE/SO/DUK/AEP/..." etc.).
    pat = re.compile(r'"[A-Z][A-Z\-\.]{0,4}/[A-Z][A-Z\-\.]{0,4}/[A-Z][A-Z\-\.]{0,4}')
    matches = pat.findall(body)
    assert not matches, f"P2.4 regression: hardcoded ticker groups back in code: {matches}"


def test_empty_themes_yaml_falls_back_to_empty_prompt(tmp_path, monkeypatch):
    """Missing yaml → empty fragment, not an exception. The surrounding
    generic prompt still constrains the LLM."""
    from stock_trading_system.data import qwen_provider as qp
    # Wipe the lru_cache so we pick up the patched loader.
    qp._load_themes.cache_clear()
    monkeypatch.setattr(qp, "_load_themes", lambda: {})
    assert qp._build_theme_prompt() == ""
    qp._load_themes.cache_clear() if hasattr(qp._load_themes, "cache_clear") else None
