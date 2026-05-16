"""P0.5 unified error handler + trace_id.

Reference: docs/test-cases/hardening-iteration-v1.md §5 (TC-HD-C5-1..5).

Goals:
    - 500 responses never leak the exception's ``str(e)``.
    - Each request has a g.trace_id reachable in logs.
    - 4xx HTTPExceptions (401 / 403 / 404 / 429 / CSRF 400) keep their
      own clean bodies.
    - grep ``return jsonify({"error": str(e)})`` 0 hits in web/app.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_500_body_does_not_leak_str_e(app_client, alice_client, monkeypatch):
    """Trigger an unhandled exception on a real route and assert the JSON
    body has trace_id + 'error':'internal' and contains NO traceback
    content. We monkeypatch the portfolio manager to raise so the global
    error handler runs in production-like fashion.

    The route ``/api/portfolio/holdings`` is the simplest victim:
    authenticated GET that delegates to ``_get_portfolio_mgr()``.
    """
    flask_app = app_client["app"]

    def _broken_get_holdings(*a, **kw):
        raise RuntimeError("super-secret-internal-detail-deadbeef")

    pm = flask_app.test_client()  # warm singletons via login flow
    from stock_trading_system.web import app as app_module
    monkeypatch.setattr(
        app_module._get_portfolio_mgr().__class__, "get_holdings",
        _broken_get_holdings,
    )

    rv = alice_client.get("/api/portfolio/holdings")
    assert rv.status_code == 500, rv.data
    body = rv.get_json() or {}
    assert body.get("error") == "internal"
    assert "super-secret-internal-detail-deadbeef" not in rv.data.decode()
    assert body.get("trace_id"), "trace_id must be in 500 body"


def test_trace_id_is_hex_uuid(app_client):
    """g.trace_id is a 32-char hex string (uuid4().hex). We assert via
    pushing a test request context and reading ``g`` directly — no
    new route required."""
    flask_app = app_client["app"]
    with flask_app.test_request_context("/api/health"):
        # Trigger the before_request handler manually.
        for handler in flask_app.before_request_funcs.get(None, []):
            if handler.__name__ == "_attach_trace_id":
                handler()
                break
        from flask import g
        assert hasattr(g, "trace_id"), "trace_id should be set"
        assert re.fullmatch(r"[0-9a-f]{32}", g.trace_id), g.trace_id


def test_trace_id_differs_per_request(app_client, alice_client):
    """Each request gets its own trace_id. We sniff trace_id from the
    response of a deliberately failing endpoint (using monkeypatch like
    test 1) — each 500 body carries its own."""
    flask_app = app_client["app"]

    from stock_trading_system.web import app as app_module
    pm_cls = app_module._get_portfolio_mgr().__class__
    orig = pm_cls.get_holdings

    def _boom(*a, **kw):
        raise RuntimeError("x")
    pm_cls.get_holdings = _boom  # type: ignore[method-assign]
    try:
        a = alice_client.get("/api/portfolio/holdings").get_json()["trace_id"]
        b = alice_client.get("/api/portfolio/holdings").get_json()["trace_id"]
        assert a != b, f"trace_ids must differ: {a} vs {b}"
    finally:
        pm_cls.get_holdings = orig  # type: ignore[method-assign]


def test_known_404_is_not_swallowed(alice_client):
    """A normal 404 keeps its own body — global handler only catches non-HTTPException."""
    rv = alice_client.get("/api/_route_that_does_not_exist_anywhere_xyz_unique")
    # The Flask catch-all may render a non-JSON 404 page (text/html).
    # What we assert: it's a 404 (not 500), and if it's JSON it doesn't
    # carry our internal-error envelope.
    assert rv.status_code in (401, 404), (
        f"non-existent /api/ path should be 404 or 401 (enforce_auth), "
        f"got {rv.status_code}"
    )
    if rv.is_json:
        body = rv.get_json() or {}
        assert body.get("error") != "internal"


def test_no_str_e_in_source(app_client):
    """DoD: grep return jsonify({"error": str(e)}) → 0 call-site hits.

    (Allows docstring mentions.)
    """
    path = Path("stock_trading_system/web/app.py")
    src = path.read_text(encoding="utf-8")
    # Strip docstrings to be tolerant of the historical mention of the
    # pattern in the unified-error-handler's own docstring.
    src_no_strings = re.sub(r'"""[\s\S]*?"""', "", src)
    pattern = re.compile(r'return\s+jsonify\([^)]*str\(e\)[^)]*\)')
    hits = pattern.findall(src_no_strings)
    assert hits == [], (
        f"Found {len(hits)} remaining 'return jsonify(...str(e)...)' "
        f"call-sites — they leak provider/path info. Hits: {hits[:3]}"
    )
