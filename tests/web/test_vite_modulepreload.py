"""vite_assets() returns a single entry + preload list, and the
layout template emits one <script type="module"> for the entry plus
modulepreload links for its dependency graph.

The old shape ran every chunk through the same <script> loop, which
forced sequential network discovery. The v1.16 split lets the browser
fan out fetches for the whole import graph in parallel while keeping
execution order correct.
"""

from __future__ import annotations

import json
from pathlib import Path

from stock_trading_system.web.vite_helpers import vite_assets


def _write_manifest(tmp_path: Path) -> Path:
    """Build a minimal manifest with one entry that imports two chunks
    plus a CSS file and a dynamic-import target. Returns the manifest path."""
    manifest = {
        "src/islands/dashboard/main.tsx": {
            "file": "assets/dashboard-X.js",
            "isEntry": True,
            "imports": ["_card-Y.js", "_chart-Z.js"],
            "dynamicImports": ["src/lib/echarts.ts"],
            "css": ["assets/style-A.css"],
        },
        "_card-Y.js": {
            "file": "assets/card-Y.js",
            "imports": [],
            "css": ["assets/card-A.css"],
        },
        "_chart-Z.js": {
            "file": "assets/chart-Z.js",
            "imports": [],
            "dynamicImports": ["src/lib/echarts.ts"],
        },
        "src/lib/echarts.ts": {
            "file": "assets/echarts-W.js",
            "imports": ["_echarts-vendor.js"],
        },
        "_echarts-vendor.js": {"file": "assets/echarts-vendor.js"},
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest))
    return p


def test_vite_assets_separates_entry_and_preloads(tmp_path, monkeypatch):
    p = _write_manifest(tmp_path)
    monkeypatch.setattr("stock_trading_system.web.vite_helpers.MANIFEST_PATH", p)
    monkeypatch.setattr(
        "stock_trading_system.web.vite_helpers._manifest_cache", None,
    )
    monkeypatch.setattr("stock_trading_system.web.vite_helpers.VITE_DEV", False)
    out = vite_assets("src/islands/dashboard/main.tsx")
    # Entry is the single <script> the layout emits.
    assert out["entry"] == "/static/dist/assets/dashboard-X.js"
    # Preloads cover the static-import graph but NOT the entry itself.
    assert "/static/dist/assets/card-Y.js" in out["preloads"]
    assert "/static/dist/assets/chart-Z.js" in out["preloads"]
    assert out["entry"] not in out["preloads"]
    # CSS bubbles up from every chunk in the graph.
    assert "/static/dist/assets/style-A.css" in out["css"]
    assert "/static/dist/assets/card-A.css" in out["css"]
    # Legacy js list still works.
    assert out["entry"] in out["js"]
    assert out["js"][-1] == out["entry"]


def test_vite_assets_excludes_dynamic_imports_from_preload(tmp_path, monkeypatch):
    """Lazy chunks (echarts, MarkdownBody, TVChart) MUST NOT appear in
    the modulepreload list — that would defeat the lazy split by
    making the browser fetch them on every page load."""
    p = _write_manifest(tmp_path)
    monkeypatch.setattr("stock_trading_system.web.vite_helpers.MANIFEST_PATH", p)
    monkeypatch.setattr(
        "stock_trading_system.web.vite_helpers._manifest_cache", None,
    )
    monkeypatch.setattr("stock_trading_system.web.vite_helpers.VITE_DEV", False)
    out = vite_assets("src/islands/dashboard/main.tsx")
    # echarts is reachable only via dynamicImports — MUST NOT preload.
    assert "/static/dist/assets/echarts-W.js" not in out["preloads"]
    assert "/static/dist/assets/echarts-vendor.js" not in out["preloads"]


def test_vite_assets_dev_mode_emits_client_and_entry(monkeypatch):
    monkeypatch.setattr("stock_trading_system.web.vite_helpers.VITE_DEV", True)
    out = vite_assets("src/islands/dashboard/main.tsx")
    assert out["dev"] is True
    assert any("@vite/client" in u for u in out["js"])
    assert out["preloads"] == []  # Vite dev handles its own preload graph
