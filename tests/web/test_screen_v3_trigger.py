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


# ── screener-v3 v1.4 — strict trigger validation ─────────────────────


def test_trigger_rejects_unknown_guru_id(alice_client):
    """An unknown guru id used to be silently dropped, leaving the run
    with fewer scorers than the user picked (and in the worst case zero
    scorers + empty results). Now we 400 and surface the offending
    list so the front-end can show the user which checkbox is wrong."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us",
        "gurus": ["buffett", "fakeguru", "another_typo"],
        "candidate_n": 10, "mode": "agent",
    })
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_guru"
    assert sorted(body["unknown"]) == ["another_typo", "fakeguru"]


def test_trigger_rejects_invalid_candidate_n(alice_client):
    """``candidate_n`` outside {10, 20, 30, 50} would either OOM the
    universe filter (huge values) or silently get capped server-side
    (small values). 400 with the allowed list."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett"],
        "candidate_n": 17, "mode": "agent",
    })
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_candidate_n"
    assert body["received"] == 17
    assert body["allowed"] == [10, 20, 30, 50]


def test_trigger_rejects_non_int_candidate_n(alice_client):
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett"],
        "candidate_n": "twenty", "mode": "agent",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_candidate_n"


def test_trigger_rejects_invalid_mode(alice_client):
    """Pre-v1.4 unknown modes silently fell through to ``agent``,
    confusing the user about which mode actually ran."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett"],
        "candidate_n": 10, "mode": "experimental_x",
    })
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_mode"
    assert body["received"] == "experimental_x"
    assert body["allowed"] == ["classic", "agent", "agent_rt"]


def test_trigger_rejects_roundtable_with_non_agent_rt_mode(alice_client):
    """``with_roundtable=true`` outside ``agent_rt`` is a request shape
    the caller must fix — silently honouring it produced UI banners
    that lied about which mode actually ran."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett"],
        "candidate_n": 10, "mode": "agent",
        "with_roundtable": True,
    })
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_roundtable"
    assert body["mode"] == "agent"


def test_trigger_accepts_agent_rt_with_or_without_explicit_flag(alice_client):
    """``mode=agent_rt`` without ``with_roundtable`` is auto-corrected
    (mode wins). Caller doesn't need to remember to set both."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett"],
        "candidate_n": 10, "mode": "agent_rt",
        # with_roundtable intentionally omitted
    })
    assert resp.status_code == 200
    assert resp.get_json()["estimated"]["with_roundtable"] is True


def test_trigger_accepts_classic_mode(alice_client):
    """Classic mode is a real path post-v1.4 (real V2 threshold gurus)."""
    resp = alice_client.post("/api/screen/v3/trigger", json={
        "market": "us", "gurus": ["buffett", "graham", "lynch"],
        "candidate_n": 10, "mode": "classic",
    })
    assert resp.status_code == 200
    assert resp.get_json()["estimated"]["mode"] == "classic"
