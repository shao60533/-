"""/api/screen/v3/trigger guards: empty gurus / invalid market.

The form was previously accepting any payload — empty gurus produced a
silent no-op, and invalid markets just got passed to the worker which
then crashed deep inside the pipeline. Both cases now 400 fast with a
human-readable message.
"""

from __future__ import annotations


def test_trigger_rejects_empty_gurus(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger",
                              json={"market": "us", "gurus": []})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "gurus_required"
    assert "至少" in body["message"]


def test_trigger_rejects_missing_gurus(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger",
                              json={"market": "us"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "gurus_required"


def test_trigger_rejects_only_blank_strings(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger",
                              json={"market": "us", "gurus": ["", " ", None]})
    assert resp.status_code == 400


def test_trigger_rejects_invalid_market(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger",
                              json={"market": "xx", "gurus": ["buffett"]})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_market"


def test_trigger_accepts_valid_payload(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett", "graham"],
        "candidate_n": 10, "mode": "agent", "with_roundtable": False,
        "nl_query": "AI 龙头",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("task_id")
    assert body["estimated"]["market"] == "us"
    assert body["estimated"]["gurus"] == ["buffett", "graham"]


def test_trigger_normalises_market_case(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "CN", "gurus": ["buffett"],
    })
    assert resp.status_code == 200
    assert resp.get_json()["estimated"]["market"] == "cn"


def test_trigger_passes_market_to_estimate(alice_client):
    """Estimate endpoint must accept and use the market field too."""
    resp = alice_client.post("/api/screen/v3/estimate", json={
        "market": "hk", "gurus": ["buffett"], "candidate_n": 20,
        "with_roundtable": False,
    })
    # The route doesn't strictly validate market today, but it must at
    # least accept the field without 500.
    assert resp.status_code == 200
