"""E of v1.14: export / bookmark / track endpoint contracts."""

from __future__ import annotations

import sqlite3

import pytest


def _seed(app_client, *, owner_id: int, ticker="AAPL") -> int:
    from stock_trading_system.portfolio.database import PortfolioDatabase
    db = PortfolioDatabase(app_client["db_path"])
    return db.save_analysis({
        "ticker": ticker, "date": "2026-04-30", "signal": "BUY",
        "market_report": "## Market\n- moving averages aligned",
        "fundamentals_report": "## Fundamentals\n- ROE 25%",
        "news_report": "no major news",
        "trade_decision": "## Decision\n- enter on dip",
        "advice_json": "",
        "created_by": owner_id,
        "provider": "qwen", "model": "qwen-plus",
        "config_hash": "cafe1234abcd0000",
        "task_id": "fake-task",
        "duration_sec": 42.0,
    })


@pytest.fixture
def alice(app_client):
    users = app_client["users"]
    return app_client["make_client"](users.alice_email, users.alice_password)


# ── Export ───────────────────────────────────────────────────────────────────


def test_export_markdown(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    rv = alice.get(f"/api/history/{aid}/export?format=md")
    assert rv.status_code == 200
    assert rv.mimetype == "text/markdown"
    body = rv.data.decode("utf-8")
    assert body.startswith("# AAPL · AI 分析")
    # Each section header should appear in the rendered markdown
    for header in ("市场 / 技术面", "基本面", "决策"):
        assert header in body
    assert 'attachment; filename="AAPL-2026-04-30.md"' in rv.headers.get(
        "Content-Disposition", "",
    )


def test_export_unknown_format_400(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    rv = alice.get(f"/api/history/{aid}/export?format=docx")
    assert rv.status_code == 400


def test_export_missing_404(alice):
    rv = alice.get("/api/history/9999999/export?format=md")
    assert rv.status_code == 404


def test_export_pdf_returns_501_when_weasyprint_absent(alice, app_client, monkeypatch):
    """We don't ship weasyprint as a hard dep; missing import → 501."""
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name in ("weasyprint", "markdown"):
            raise ImportError(f"forced absence of {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rv = alice.get(f"/api/history/{aid}/export?format=pdf")
    assert rv.status_code == 501
    assert rv.get_json()["error"] == "pdf_unavailable"


# ── Bookmark toggle ──────────────────────────────────────────────────────────


def test_bookmark_toggle_round_trip(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    on = alice.post(f"/api/history/{aid}/bookmark", json={"bookmarked": True})
    assert on.status_code == 200 and on.get_json()["bookmarked"] is True

    off = alice.post(f"/api/history/{aid}/bookmark", json={"bookmarked": False})
    assert off.status_code == 200 and off.get_json()["bookmarked"] is False

    # State reflected on /api/history/<id>
    detail = alice.get(f"/api/history/{aid}").get_json()
    assert detail["bookmarked"] is False


def test_bookmark_unknown_id_404(alice):
    rv = alice.post("/api/history/9999999/bookmark", json={"bookmarked": True})
    assert rv.status_code == 404


# ── Watchlist track ──────────────────────────────────────────────────────────


def test_track_writes_user_watchlist(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    rv = alice.post(
        "/api/portfolio/track",
        json={"ticker": "aapl", "analysis_id": aid},
    )
    assert rv.status_code == 200
    assert rv.get_json()["ticker"] == "AAPL"

    conn = sqlite3.connect(app_client["db_path"])
    rows = conn.execute(
        "SELECT user_id, ticker, analysis_id FROM user_watchlist"
    ).fetchall()
    conn.close()
    assert (app_client["users"].alice.id, "AAPL", aid) in rows


def test_track_idempotent(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    alice.post("/api/portfolio/track", json={"ticker": "AAPL", "analysis_id": aid})
    alice.post("/api/portfolio/track", json={"ticker": "AAPL", "analysis_id": aid})

    conn = sqlite3.connect(app_client["db_path"])
    cnt = conn.execute(
        "SELECT COUNT(*) FROM user_watchlist WHERE user_id = ? AND ticker = ?",
        (app_client["users"].alice.id, "AAPL"),
    ).fetchone()[0]
    conn.close()
    assert cnt == 1


def test_track_requires_ticker(alice):
    rv = alice.post("/api/portfolio/track", json={"analysis_id": 1})
    assert rv.status_code == 400


# ── /api/history listing carries created_by_name ────────────────────────────


def test_history_listing_includes_creator_name(alice, app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    rv = alice.get("/api/history?limit=5")
    assert rv.status_code == 200
    body = rv.get_json()
    items = body.get("items") or body.get("records") or []
    assert any(r["id"] == aid for r in items)
    target = next(r for r in items if r["id"] == aid)
    assert target["created_by_name"] == "alice"


# ── Anonymous calls denied ───────────────────────────────────────────────────


def test_anonymous_export_denied(app_client):
    aid = _seed(app_client, owner_id=app_client["users"].alice.id)
    anon = app_client["make_client"]()
    rv = anon.get(f"/api/history/{aid}/export?format=md")
    assert rv.status_code in (302, 401)


def test_anonymous_bookmark_denied(app_client):
    anon = app_client["make_client"]()
    rv = anon.post("/api/history/1/bookmark", json={"bookmarked": True})
    assert rv.status_code == 401


def test_anonymous_track_denied(app_client):
    anon = app_client["make_client"]()
    rv = anon.post("/api/portfolio/track", json={"ticker": "AAPL", "analysis_id": 1})
    assert rv.status_code == 401
