"""Vite ↔ Flask integration helpers.

Reads the Vite manifest.json to map entry points to their hashed
JS/CSS output files. In dev mode, points to the Vite dev server.
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
    """Return {'js': [...], 'css': [...], 'dev': bool} for a given entry.

    entry examples: 'src/islands/screener-v3/main.tsx'
    """
    if VITE_DEV:
        return {
            "js": [
                f"{VITE_DEV_URL}/@vite/client",
                f"{VITE_DEV_URL}/{entry}",
            ],
            "css": [],
            "dev": True,
        }

    # Prod: read manifest
    global _manifest_cache
    if _manifest_cache is None:
        if not MANIFEST_PATH.exists():
            return {"js": [], "css": [], "dev": False, "error": "manifest not found"}
        _manifest_cache = json.loads(MANIFEST_PATH.read_text())

    manifest = _manifest_cache
    item = manifest.get(entry)
    if not item:
        return {"js": [], "css": [], "dev": False, "error": f"entry {entry} not in manifest"}

    result: dict = {"js": [f"/static/dist/{item['file']}"], "css": [], "dev": False}
    for css in item.get("css", []):
        result["css"].append(f"/static/dist/{css}")
    # Imports (chunk split)
    for imp in item.get("imports", []):
        if imp in manifest:
            result["js"].insert(0, f"/static/dist/{manifest[imp]['file']}")
    return result
