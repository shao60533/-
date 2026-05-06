"""v1.0.3 [#4] — /api/analyze must honor the v2.1 depth two-state
contract (``deep_analysis`` boolean canonical, ``depth`` string for
backwards compat).

Pre-fix: the route only read ``data.get("depth")`` via the legacy
``_normalize_depth(str)`` coercer, so a client sending the new
``deep_analysis: True`` boolean (as the React Switch does) had its
toggle dropped on the floor and the worker fell back to ``standard``.
Now /api/analyze runs the same ``normalize_analysis_depth(params)``
helper that the analysis worker uses.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app_client, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


def _submitted_params(monkeypatch) -> list[dict]:
    """Capture the params dict the route hands off to TaskManager.submit
    so we can assert what depth ended up there. Returns a list (mutable
    closure) the caller pokes at after the request resolves."""
    captured: list[dict] = []

    def _fake_submit(self, task_type, params, **kwargs):
        captured.append(dict(params))
        return {"id": "t-test", "type": task_type, "params": params,
                "status": "pending"}

    from stock_trading_system.tasks.task_manager import TaskManager
    monkeypatch.setattr(TaskManager, "submit", _fake_submit, raising=True)
    return captured


def test_api_analyze_deep_analysis_true_routes_deep(client, monkeypatch):
    """deep_analysis=True (canonical wire shape) → params['depth']='deep'."""
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "deep_analysis": True},
    )
    assert resp.status_code == 200, resp.get_json()
    assert captured, "TaskManager.submit was never called"
    p = captured[-1]
    assert p["depth"] == "deep", p
    assert p["deep_analysis"] is True, p


def test_api_analyze_deep_analysis_false_routes_standard(client, monkeypatch):
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "deep_analysis": False},
    )
    assert resp.status_code == 200
    p = captured[-1]
    assert p["depth"] == "standard", p
    assert p["deep_analysis"] is False, p


def test_api_analyze_legacy_depth_quick_collapses_to_standard(
    client, monkeypatch,
):
    """Stale clients that still send ``depth='quick'`` (no boolean)
    must NOT carry the deprecated value forward — normalize_analysis_depth
    coerces quick → standard."""
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "depth": "quick"},
    )
    assert resp.status_code == 200
    p = captured[-1]
    assert p["depth"] == "standard", p
    assert p["deep_analysis"] is False, p


def test_api_analyze_legacy_depth_deep_routes_deep(client, monkeypatch):
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "depth": "deep"},
    )
    assert resp.status_code == 200
    p = captured[-1]
    assert p["depth"] == "deep"
    assert p["deep_analysis"] is True


def test_api_analyze_boolean_wins_over_legacy_string(client, monkeypatch):
    """Frontend transition window sends BOTH for one release (safety
    net). Boolean must override the legacy string."""
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "deep_analysis": True, "depth": "standard"},
    )
    assert resp.status_code == 200
    assert captured[-1]["depth"] == "deep"


def test_api_analyze_empty_body_defaults_standard(client, monkeypatch):
    """No depth fields → default standard (NOT quick)."""
    captured = _submitted_params(monkeypatch)
    resp = client.post(
        "/api/analyze",
        json={"ticker": "AAPL"},
    )
    assert resp.status_code == 200
    p = captured[-1]
    assert p["depth"] == "standard"
    assert p["deep_analysis"] is False


def test_api_analyze_anonymous_rejected(app_client):
    anon = app_client["make_client"]()
    resp = anon.post("/api/analyze", json={"ticker": "AAPL"})
    assert resp.status_code == 401
