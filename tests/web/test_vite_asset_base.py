"""Vite asset-base regression: production preload helper must build
URLs against ``/static/dist/`` (the Flask mount point), not the
default ``/`` root.

Why this test exists: AnalysisPage uses ``React.lazy(() => import(...))``
to defer the structured-card bundle. When that dynamic import runs,
Vite's bundled ``__vitePreload`` helper builds CSS/JS preload URLs by
prepending ``base`` (configured in ``vite.config.ts``) to the chunk's
relative path. The default ``base`` is ``/``, which produces
``/assets/card-XYZ.css`` — but Flask serves dist under ``/static/dist/``,
so the browser fetches a 404, the dynamic import rejects with
``Unable to preload CSS for /assets/card-*.css``, the per-tab
ErrorBoundary catches it, and the user sees "结构化摘要组件加载失败"
even though the structured data itself is fine.

The fix is ``base: "/static/dist/"`` in ``vite.config.ts``. This test
locks the contract so a future tweak to vite.config that drops or
breaks ``base`` is caught before deploy.

The build artefact (``stock_trading_system/web/static/dist/``) is
checked in for Railway deploys, so we can scan the built JS directly
without rebuilding here.
"""

from __future__ import annotations

import json
from pathlib import Path


DIST_DIR = (
    Path(__file__).resolve().parents[2]
    / "stock_trading_system" / "web" / "static" / "dist" / "assets"
)


def _preload_helper_files() -> list[Path]:
    """Find the ``preload-helper-*.js`` chunk Vite emits. There is
    exactly one in a healthy build. Returning a list lets the test
    surface a clearer failure when the chunk is missing entirely
    (vite.config regression that disables ``preload-helper`` would
    otherwise read as a "no test ran" silence)."""
    return sorted(DIST_DIR.glob("preload-helper-*.js"))


def test_preload_helper_chunk_exists():
    """Sanity: the chunk must be in the build. If this fails, the
    build was never run (deploys ship the checked-in dist)."""
    files = _preload_helper_files()
    assert files, (
        f"No preload-helper-*.js found in {DIST_DIR}. Run "
        "`cd stock_trading_system/web/frontend && npm run build` first."
    )
    assert len(files) == 1, (
        f"Expected exactly one preload-helper chunk, found {len(files)}: "
        f"{[f.name for f in files]}. Stale builds can leak into the dist; "
        "rebuild from a clean tree."
    )


def test_preload_helper_uses_static_dist_base():
    """The minified chunk contains an inline URL builder of the form
    ``return"/static/dist/"+i`` (or similar). The default Vite output
    is ``return"/"+i`` which is the regression vector. Assert the
    correct base prefix is baked into the helper.
    """
    [helper] = _preload_helper_files()
    text = helper.read_text(encoding="utf-8")
    assert '"/static/dist/"' in text, (
        f"preload-helper does NOT contain '/static/dist/' base — "
        f"vite.config.ts ``base`` is missing or set wrong. The chunk "
        f"will produce 404s for dynamic CSS/JS imports in production. "
        f"Fix: set ``base: \"/static/dist/\"`` in vite.config.ts and "
        f"rebuild. Current chunk head:\n{text[:400]}"
    )
    # Regression guard: the default-Vite ``return"/"+i`` form must not
    # be present anywhere in the helper body. We look for the exact
    # minifier-output marker so a constant string ``"/"`` elsewhere
    # (e.g. ``rel="stylesheet"`` URL construction) doesn't false-match.
    assert 'return"/"+' not in text, (
        f"preload-helper still has the default ``base: '/'`` URL "
        f"builder. The Vite ``base`` setting was reverted or "
        f"ineffective. Chunk head:\n{text[:400]}"
    )


def test_no_bare_assets_url_in_built_chunks():
    """Defence in depth: scan every built JS chunk for a hard-coded
    bare ``"/assets/"`` URL. This would also produce 404s in
    production. The base setting on vite.config.ts should prevent any
    bundled module from emitting one — but Tailwind-emitted CSS,
    third-party libs, or future config changes might bake a bare
    asset path into the bundle. Catch it at test time.

    We only flag the exact prefix ``"/assets/`` (including the leading
    quote so we don't false-match on relative ``./assets/``,
    ``../assets/``, or substrings like ``module/assets/`` — those are
    fine because Vite resolves them against ``base`` at runtime).
    """
    bad: list[tuple[str, str]] = []
    for js in DIST_DIR.glob("*.js"):
        text = js.read_text(encoding="utf-8")
        if '"/assets/' not in text:
            continue
        idx = text.find('"/assets/')
        ctx = text[max(0, idx - 40):idx + 80]
        bad.append((js.name, ctx))
    assert not bad, (
        "Bare /assets/ URLs leaked into the built bundle — they will "
        "404 in production because Flask serves dist under "
        "/static/dist/. Offenders:\n" +
        "\n".join(f"  {name}: …{ctx}…" for name, ctx in bad)
    )


def test_modulepreload_helper_does_not_double_prefix():
    """The Python ``vite_helpers.py`` ALSO prepends ``/static/dist/``
    when generating <link rel="modulepreload"> URLs. A naive fix that
    rewrote manifest paths to absolute ``/static/dist/...`` would
    cause the helper to double-prefix to ``/static/dist/static/dist/...``.

    Verify the manifest still emits relative paths (``assets/foo.js``,
    not ``/static/dist/assets/foo.js``) so vite_helpers.py keeps
    working without modification.
    """
    manifest_path = DIST_DIR.parent / ".vite" / "manifest.json"
    assert manifest_path.exists(), f"Missing manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    leaked = [
        (k, v["file"]) for k, v in manifest.items()
        if isinstance(v, dict) and isinstance(v.get("file"), str)
        and v["file"].startswith("/")
    ]
    assert not leaked, (
        "Manifest entries must use paths relative to outDir (e.g. "
        "``assets/foo.js``). Absolute paths would cause "
        "``vite_helpers.py`` to emit URLs like "
        "``/static/dist//static/dist/assets/foo.js``. Offenders: "
        f"{leaked}"
    )
