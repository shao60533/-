"""resolve_openrouter_model — preset pool resolver invariants.

docs/design/llm-openrouter.md v1.0 §2.6 — 4 cases:
    1. active.deep matches a preset → returns that preset
    2. active.deep points to nonexistent id → falls to first matching role
    3. presets list empty → safe default; no exception
    4. provider_order + kwargs round-trip through normalisation
"""

from __future__ import annotations

import pytest

from stock_trading_system.llm.router import (
    _HARDCODED_FALLBACK,
    resolve_openrouter_model,
)


def test_active_deep_pointer_resolves_to_named_preset():
    cfg = {
        "openrouter": {
            "presets": [
                {"id": "p1", "label": "Pro 1", "model": "vendor/p1", "role": "deep"},
                {"id": "p2", "label": "Pro 2", "model": "vendor/p2", "role": "deep"},
            ],
            "active": {"deep": "p2"},
        },
    }
    out = resolve_openrouter_model(cfg, role="deep")
    assert out["id"] == "p2"
    assert out["model"] == "vendor/p2"
    assert out["label"] == "Pro 2"


def test_dangling_active_pointer_falls_through_to_first_match():
    """active.deep points at an id that doesn't exist anymore (e.g. user
    deleted the preset but yaml's active block wasn't updated). The
    resolver must fall through to step 3 — first preset whose role
    matches — instead of raising or returning None."""
    cfg = {
        "openrouter": {
            "presets": [
                {"id": "p1", "label": "Pro 1", "model": "vendor/p1", "role": "deep"},
                {"id": "p2", "label": "Pro 2", "model": "vendor/p2", "role": "deep"},
            ],
            "active": {"deep": "p-deleted"},
        },
    }
    out = resolve_openrouter_model(cfg, role="deep")
    assert out["id"] == "p1"  # first matching role wins


def test_empty_presets_returns_safe_default_without_raising():
    """No presets at all → the hardcoded fallback. Ships a working
    OpenAI-compatible model id even when the registry is broken."""
    cfg = {"openrouter": {"presets": [], "active": {}}}
    out = resolve_openrouter_model(cfg, role="deep")
    assert out["model"] == _HARDCODED_FALLBACK["deep"]["model"]
    assert out["id"] == _HARDCODED_FALLBACK["deep"]["id"]


def test_provider_order_and_kwargs_roundtrip():
    """Both fields must survive normalisation as proper Python list/dict
    (not the raw yaml node) so downstream callers can mutate without
    aliasing the registry."""
    cfg = {
        "openrouter": {
            "presets": [{
                "id": "p1",
                "label": "Pro",
                "model": "vendor/p1",
                "role": "deep",
                "provider_order": ["v1", "v2"],
                "kwargs": {"temperature": 0.7, "max_tokens": 4000},
            }],
            "active": {"deep": "p1"},
        },
    }
    out = resolve_openrouter_model(cfg, role="deep")
    assert out["provider_order"] == ["v1", "v2"]
    assert out["kwargs"] == {"temperature": 0.7, "max_tokens": 4000}
    # mutate output → registry unchanged
    out["provider_order"].append("mutation")
    out["kwargs"]["new"] = 1
    cfg_preset = cfg["openrouter"]["presets"][0]
    assert cfg_preset["provider_order"] == ["v1", "v2"]
    assert "new" not in cfg_preset["kwargs"]


def test_role_both_matches_either_role():
    """A preset declared with role='both' should match deep AND quick
    role queries. Used for compact yaml where one model serves both
    paths (e.g. testing / ollama)."""
    cfg = {
        "openrouter": {
            "presets": [
                {"id": "uni", "label": "Universal",
                 "model": "vendor/uni", "role": "both"},
            ],
            "active": {},  # no role pointers — exercises the
                            # "first matching role" fall-through
        },
    }
    deep  = resolve_openrouter_model(cfg, role="deep")
    quick = resolve_openrouter_model(cfg, role="quick")
    assert deep["id"] == "uni"
    assert quick["id"] == "uni"
