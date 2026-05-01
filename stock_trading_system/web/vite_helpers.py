"""Vite ↔ Flask integration helpers.

Reads the Vite manifest.json to map entry points to their hashed
JS/CSS output files. In dev mode, points to the Vite dev server.

v1.16 split entries vs preloads so the layout template can emit only
ONE ``<script type="module">`` for the entry chunk and a list of
``<link rel="modulepreload">`` for its dependency graph. Previously
every chunk was rendered as a top-level <script>, which meant the
browser had to wait for each script's fetch+parse before discovering
the next one. modulepreload lets the browser fan out the fetches in
parallel without executing them ahead of the entry's static-import
order.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

VITE_DEV = os.environ.get("FLASK_ENV") == "development"
VITE_DEV_URL = "http://localhost:5173"
DIST_DIR = Path(__file__).parent / "static" / "dist"
MANIFEST_PATH = DIST_DIR / ".vite" / "manifest.json"

_manifest_cache: dict | None = None


def vite_assets(entry: str) -> dict:
    """Return ``{entry, preloads, css, dev, js}`` for a given entry.

    Keys:
        * ``entry``    — single JS URL for the entry chunk's <script>
        * ``preloads`` — JS URLs for chunks the entry statically imports
                          (transitive). Emitted as <link rel="modulepreload">
                          so the browser fetches them in parallel.
        * ``css``      — CSS URLs across the whole import tree.
        * ``dev``      — True in Vite dev mode (HMR-served).
        * ``js``       — legacy alias = [*preloads, entry]; kept so any
                          template that still iterates ``assets.js``
                          renders the same set in the right order.

    entry examples: 'src/islands/screener-v3/main.tsx'
    """
    if VITE_DEV:
        # Dev: Vite handles its own preload graph via @vite/client; emit
        # the client + entry as scripts and leave preloads empty.
        client = f"{VITE_DEV_URL}/@vite/client"
        entry_url = f"{VITE_DEV_URL}/{entry}"
        return {
            "entry": entry_url,
            "preloads": [],
            "css": [],
            "dev": True,
            "js": [client, entry_url],
        }

    # Prod: read manifest
    global _manifest_cache
    if _manifest_cache is None:
        if not MANIFEST_PATH.exists():
            return {
                "entry": "", "preloads": [], "css": [],
                "dev": False, "js": [],
                "error": "manifest not found",
            }
        _manifest_cache = json.loads(MANIFEST_PATH.read_text())

    manifest = _manifest_cache
    item = manifest.get(entry)
    if not item:
        return {
            "entry": "", "preloads": [], "css": [],
            "dev": False, "js": [],
            "error": f"entry {entry} not in manifest",
        }

    entry_url = f"/static/dist/{item['file']}"
    css: list[str] = [f"/static/dist/{c}" for c in item.get("css", [])]
    preloads: list[str] = []

    # Walk the static-import graph and collect transitively imported
    # chunks. Each one gets a modulepreload link AND its CSS bubbles up
    # to the head so unstyled flashes don't happen. Dynamic imports
    # (e.g. ChartPanel's lazy echarts load) are NOT in ``imports`` —
    # they only appear under ``dynamicImports`` in the manifest, which
    # we deliberately skip to keep the preload list lean.
    seen: set[str] = set()

    def _collect(chunk_key: str) -> None:
        if chunk_key in seen:
            return
        seen.add(chunk_key)
        chunk = manifest.get(chunk_key)
        if not chunk:
            return
        url = f"/static/dist/{chunk['file']}"
        if url not in preloads and url != entry_url:
            preloads.append(url)
        for c in chunk.get("css", []):
            css_url = f"/static/dist/{c}"
            if css_url not in css:
                css.append(css_url)
        for sub in chunk.get("imports", []):
            _collect(sub)

    for imp in item.get("imports", []):
        _collect(imp)

    return {
        "entry": entry_url,
        "preloads": preloads,
        "css": css,
        "dev": False,
        # Legacy alias: callers iterating ``assets.js`` still see the same
        # set of URLs in the right execution order (preloads first so
        # they parse before the entry needs them).
        "js": [*preloads, entry_url],
    }
