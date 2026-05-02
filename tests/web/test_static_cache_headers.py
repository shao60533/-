"""Static-asset cache header regression.

Vite emits chunks with content-hashed filenames (``card-DOd2UOLY.js``).
These are immutable: once a build ships, the URL never changes content.
The browser should cache them aggressively so page-to-page navigation
doesn't re-download the shared chunks.

The Flask ``after_request`` hook in
``stock_trading_system/web/app.py::add_static_asset_cache_headers`` sets:

    /static/dist/assets/*           → public, max-age=31536000, immutable
    /static/dist/.vite/manifest.json → no-store
    /static/dist/* (everything else) → public, max-age=3600

If a future config change drops or weakens these, the browser falls
back to revalidating every chunk on every page load (304s instead of
straight cache hits) and page-click latency jumps. This test pins the
exact headers so the regression surfaces in CI, not in user reports.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _any_built_chunk() -> str | None:
    """Pick a real built chunk filename so the test exercises the
    header logic against an actual served path. Returns ``None`` if
    the dist isn't built (test then skips rather than false-fails)."""
    dist = (
        Path(__file__).resolve().parents[2]
        / "stock_trading_system" / "web" / "static" / "dist" / "assets"
    )
    if not dist.exists():
        return None
    for f in dist.glob("*.js"):
        return f.name
    return None


def test_assets_get_immutable_one_year_cache(alice_client):
    """A real built chunk must be served with the immutable + 1-year
    cache directive. The hash in the filename guarantees the URL
    changes when content changes, so caching forever is safe."""
    chunk = _any_built_chunk()
    if chunk is None:
        pytest.skip("dist/ not built — run `npm run build` first")
    resp = alice_client.get(f"/static/dist/assets/{chunk}")
    # 200 because the file actually exists; 404 would mean Flask isn't
    # serving the dist correctly which is a different bug.
    assert resp.status_code == 200, (
        f"/static/dist/assets/{chunk} returned {resp.status_code}; "
        f"Flask static mount may be misconfigured."
    )
    cache = resp.headers.get("Cache-Control", "")
    assert "max-age=31536000" in cache, (
        f"Expected 1-year max-age on hashed asset, got: {cache!r}"
    )
    assert "immutable" in cache, (
        f"Expected ``immutable`` directive on hashed asset, got: {cache!r}. "
        f"Without it Safari etc. still revalidate after the tab is "
        f"reopened, defeating the long-cache goal."
    )
    assert "public" in cache, (
        f"Expected ``public`` directive (CDN-cacheable), got: {cache!r}"
    )


def test_manifest_is_never_cached(alice_client):
    """``manifest.json`` is the deploy-pivot file: it maps stable
    entry names (``analysis``, ``screener-v3``) to the current build's
    hashed chunks. If a stale copy is served, the HTML still references
    chunk filenames from the previous deploy → 404 storm. Force the
    browser/CDN to revalidate every time.
    """
    resp = alice_client.get("/static/dist/.vite/manifest.json")
    # File may not exist in some test layouts — only assert headers
    # if Flask actually returned the file.
    if resp.status_code == 404:
        pytest.skip("manifest.json not present in this build")
    assert resp.status_code == 200
    cache = resp.headers.get("Cache-Control", "")
    assert "no-store" in cache, (
        f"manifest.json must NOT be cached (got {cache!r}). A cached "
        f"manifest produces 404s after every deploy because the HTML "
        f"asks for chunk filenames the new build no longer emits."
    )
