"""v1.22: ``/history`` is folded into ``/analysis``. Old bookmarks
get a 301 with the query string preserved so deep-links keep working."""

from __future__ import annotations


def test_history_root_redirects_to_analysis(alice_client):
    resp = alice_client.get("/history", follow_redirects=False)
    assert resp.status_code == 301
    # Trailing slash isn't present in our route.
    assert resp.headers["Location"].endswith("/analysis")


def test_history_query_string_preserved(alice_client):
    """Saved /history?ticker=AAPL&signal=BUY URLs reach the inbox with
    filters applied — the inbox toolbar uses the same query syntax."""
    resp = alice_client.get(
        "/history?ticker=AAPL&signal=BUY",
        follow_redirects=False,
    )
    assert resp.status_code == 301
    assert resp.headers["Location"] == "/analysis?ticker=AAPL&signal=BUY"


def test_history_redirect_status_is_permanent(alice_client):
    """301 (permanent) — bookmark caches + search engines should
    update; not a 302 temp redirect that they'd keep re-resolving."""
    resp = alice_client.get("/history", follow_redirects=False)
    assert resp.status_code == 301
