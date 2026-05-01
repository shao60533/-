"""Unit tests for the daily_snapshots backfill migration.

We inject a fake ``fetch_history`` so the suite never hits the network.
The fake produces a synthetic OHLCV series so we can verify the algorithm
end-to-end (replay → price lookup → upsert) deterministically.
"""

from __future__ import annotations

import sqlite3
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stock_trading_system.migrations.backfill_daily_snapshots import (
    backfill_user,
    backfill_all_users,
)
from stock_trading_system.portfolio.database import PortfolioDatabase


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    """Single-user (pre-multi-tenant) DB seeded with two transactions."""
    p = tmp_path / "portfolio.db"
    PortfolioDatabase(str(p))  # creates schema
    conn = sqlite3.connect(str(p))
    # Two buys on the first day of our window
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("AAPL", "buy", 10, 150.0, "2026-04-15 10:00:00", ""),
    )
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("MSFT", "buy", 5, 350.0, "2026-04-15 10:05:00", ""),
    )
    conn.commit()
    conn.close()
    return str(p)


@pytest.fixture
def multi_tenant_db_path(tmp_path):
    """DB shape post-multi-tenant migration: user_id columns present.

    Note that ``daily_snapshots.date`` is still the sole PRIMARY KEY in this
    schema, so we deliberately seed each user's transactions on different
    dates — the snapshot table can't hold two rows for the same date until a
    separate schema change introduces a composite key. See the migration
    module docstring for the documented limitation.
    """
    p = tmp_path / "portfolio.db"
    PortfolioDatabase(str(p))
    conn = sqlite3.connect(str(p))
    # v1.16: PortfolioDatabase already provisions user_id on these
    # tables. Keep the ALTERs idempotent for older snapshots that
    # might be loaded without the multi-tenant migration.
    for table in ("transactions", "positions", "daily_snapshots"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
    # alice trades on 2026-04-14
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("NVDA", "buy", 4, 500.0, "2026-04-14 09:30:00", "", 1),
    )
    # bob trades on 2026-04-15
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("TSLA", "buy", 2, 200.0, "2026-04-15 09:30:00", "", 2),
    )
    conn.commit()
    conn.close()
    return str(p)


def _make_fake_history(close_by_ticker: dict[str, dict[date_cls, float]]):
    """Return a fetcher that produces an OHLCV DataFrame with these closes."""
    def fetch(ticker, start, end):
        if ticker == "SPY":
            # Every weekday between start and end, inclusive
            cur = start
            dates = []
            while cur <= end:
                if cur.weekday() < 5:
                    dates.append(cur)
                cur += timedelta(days=1)
            if not dates:
                return None
            idx = pd.DatetimeIndex(pd.to_datetime(dates))
            return pd.DataFrame({"Close": [400.0] * len(dates)}, index=idx)
        prices = close_by_ticker.get(ticker.upper(), {})
        if not prices:
            return None
        sorted_dates = sorted(prices.keys())
        idx = pd.DatetimeIndex(pd.to_datetime(sorted_dates))
        return pd.DataFrame(
            {"Close": [prices[d] for d in sorted_dates]},
            index=idx,
        )
    return fetch


# ── Single-user backfill ─────────────────────────────────────────────────────


def test_dry_run_writes_nothing(db_path):
    fetch = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 152.0, date_cls(2026, 4, 16): 153.0},
        "MSFT": {date_cls(2026, 4, 15): 351.0, date_cls(2026, 4, 16): 352.0},
    })
    res = backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 16),
        dry_run=True,
        fetch_history=fetch,
    )
    assert res["status"] == "ok"
    assert res["backfilled"] == 2
    # No rows actually written
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM daily_snapshots").fetchone()[0]
    conn.close()
    assert n == 0


def test_writes_rows_in_ascending_order(db_path):
    fetch = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 152.0, date_cls(2026, 4, 16): 154.0},
        "MSFT": {date_cls(2026, 4, 15): 351.0, date_cls(2026, 4, 16): 360.0},
    })
    res = backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 16),
        fetch_history=fetch,
    )
    assert res["backfilled"] == 2
    assert res["failed"] == 0

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT date, total_value, total_cost, pnl FROM daily_snapshots ORDER BY date ASC"
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["2026-04-15", "2026-04-16"]

    # 2026-04-15 holdings: 10 AAPL @ 152 + 5 MSFT @ 351 = 1520 + 1755 = 3275
    # cost = 10*150 + 5*350 = 1500 + 1750 = 3250  → pnl = 25
    assert rows[0][1] == pytest.approx(3275.0)
    assert rows[0][2] == pytest.approx(3250.0)
    assert rows[0][3] == pytest.approx(25.0)

    # 2026-04-16: 10 AAPL @ 154 + 5 MSFT @ 360 = 1540 + 1800 = 3340; pnl = 90
    assert rows[1][1] == pytest.approx(3340.0)
    assert rows[1][3] == pytest.approx(90.0)


def test_idempotent_skip(db_path):
    """Re-running should report skipped rows, not new inserts."""
    fetch = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 152.0},
        "MSFT": {date_cls(2026, 4, 15): 351.0},
    })
    backfill_user(db_path, None, today=date_cls(2026, 4, 15), fetch_history=fetch)
    res2 = backfill_user(db_path, None, today=date_cls(2026, 4, 15), fetch_history=fetch)
    assert res2["backfilled"] == 0
    assert res2["skipped"] == 1


def test_force_overwrites(db_path):
    """--force should rewrite an existing snapshot."""
    fetch1 = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 100.0},
        "MSFT": {date_cls(2026, 4, 15): 200.0},
    })
    fetch2 = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 999.0},
        "MSFT": {date_cls(2026, 4, 15): 999.0},
    })
    backfill_user(db_path, None, today=date_cls(2026, 4, 15), fetch_history=fetch1)
    res = backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 15),
        fetch_history=fetch2,
        force=True,
    )
    assert res["backfilled"] == 1
    conn = sqlite3.connect(db_path)
    val = conn.execute(
        "SELECT total_value FROM daily_snapshots WHERE date = '2026-04-15'"
    ).fetchone()[0]
    conn.close()
    # 10*999 + 5*999 = 14985
    assert val == pytest.approx(14985.0)


def test_fallback_to_previous_close(db_path, caplog):
    """When yfinance has no row for the target day, walk back and warn."""
    fetch = _make_fake_history({
        # 4/15 has prices, 4/16 is missing for both tickers; algorithm should
        # walk back to 4/15 and emit a warning.
        "AAPL": {date_cls(2026, 4, 15): 152.0},
        "MSFT": {date_cls(2026, 4, 15): 351.0},
    })
    import logging
    caplog.set_level(logging.WARNING)
    res = backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 16),
        fetch_history=fetch,
    )
    assert res["backfilled"] == 2
    assert res["fallback_prices"] >= 1
    fallback_msgs = [r.message for r in caplog.records
                     if "used most recent prior close" in r.message]
    assert fallback_msgs, "expected a fallback-warning log line"


def test_no_price_falls_back_to_cost_basis(db_path, caplog):
    """No close in window but cost basis available → cost_basis_fallback,
    snapshot row still written so the curve stays continuous.

    v1.16: hand-typed test tickers (TEST1/TESTX/ZZZTEST) used to abort
    the whole day's backfill the moment one ticker had no yfinance
    coverage. Now we value those positions at avg_cost and surface
    them via ``missing_prices`` + ``fallback_prices_by_ticker``.
    """
    fetch = _make_fake_history({})  # no prices at all
    import logging
    import json
    caplog.set_level(logging.WARNING)
    res = backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 15),
        fetch_history=fetch,
    )
    # Cost basis fallback covered both AAPL and MSFT — day still backfilled.
    assert res["backfilled"] == 1
    assert res["failed"] == 0
    assert res["fallback_prices"] >= 2
    assert set(res["missing_prices"]) == {"AAPL", "MSFT"}
    assert res["skipped_tickers"] == []
    assert res["fallback_prices_by_ticker"] == {
        "AAPL": "cost_basis_fallback", "MSFT": "cost_basis_fallback",
    }
    # positions_json carries the per-ticker price_source.
    conn = sqlite3.connect(db_path)
    pj = conn.execute(
        "SELECT positions_json FROM daily_snapshots WHERE date = '2026-04-15'"
    ).fetchone()[0]
    conn.close()
    pos = json.loads(pj)
    assert all(p["price_source"] == "cost_basis_fallback" for p in pos)
    fallback_msgs = [r.message for r in caplog.records
                     if "cost_basis_fallback" in r.message]
    assert fallback_msgs


def test_failed_when_all_positions_unvalueable(tmp_path, caplog):
    """Genuine fail case: shares > 0 but cost_basis = 0 (price=0 buy)
    AND no yfinance coverage. Nothing to anchor a value to → day fails
    with no row written, so the curve doesn't lie about the position."""
    import logging
    import sqlite3
    p = tmp_path / "p.db"
    PortfolioDatabase(str(p))
    conn = sqlite3.connect(str(p))
    # Both txns have price=0 → cost_basis stays 0, can't fall back.
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES ('GHOST', 'buy', 10, 0.0, '2026-04-15 10:00:00', '')"
    )
    conn.commit()
    conn.close()
    fetch = _make_fake_history({})  # no closes either
    caplog.set_level(logging.WARNING)
    res = backfill_user(
        str(p), None,
        today=date_cls(2026, 4, 15),
        fetch_history=fetch,
    )
    assert res["failed"] == 1
    assert res["backfilled"] == 0
    assert res["skipped_tickers"] == ["GHOST"]
    assert res["missing_prices"] == ["GHOST"]


def test_partial_miss_does_not_skip_other_tickers(tmp_path):
    """One ticker with no yfinance and no cost basis is skipped; the
    other ticker still produces a snapshot for the same day."""
    import json
    import sqlite3
    p = tmp_path / "p.db"
    PortfolioDatabase(str(p))
    conn = sqlite3.connect(str(p))
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES ('AAPL', 'buy', 10, 150.0, '2026-04-15 10:00:00', '')"
    )
    # GHOST: shares but zero cost basis → unvalueable.
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES ('GHOST', 'buy', 5, 0.0, '2026-04-15 10:05:00', '')"
    )
    conn.commit()
    conn.close()
    fetch = _make_fake_history({"AAPL": {date_cls(2026, 4, 15): 200.0}})
    res = backfill_user(
        str(p), None,
        today=date_cls(2026, 4, 15),
        fetch_history=fetch,
    )
    # Day still written — AAPL valued at 200.
    assert res["backfilled"] == 1
    assert res["failed"] == 0
    assert "GHOST" in res["skipped_tickers"]
    conn = sqlite3.connect(str(p))
    row = conn.execute(
        "SELECT total_value, positions_json FROM daily_snapshots WHERE date = '2026-04-15'"
    ).fetchone()
    conn.close()
    assert row[0] == pytest.approx(2000.0)  # 10 AAPL * 200
    pos = json.loads(row[1])
    by_ticker = {p["ticker"]: p for p in pos}
    assert by_ticker["AAPL"]["price_source"] == "close"
    assert by_ticker["GHOST"]["price_source"] == "missing_skipped"


# ── Multi-user driver ────────────────────────────────────────────────────────


def test_backfill_all_users_legacy_db_falls_back(tmp_path):
    """No users table → single-user backfill path."""
    p = tmp_path / "legacy.db"
    PortfolioDatabase(str(p))
    conn = sqlite3.connect(str(p))
    conn.execute(
        "INSERT INTO transactions(ticker, action, shares, price, timestamp, notes) "
        "VALUES ('AAPL', 'buy', 1, 100.0, '2026-04-15 10:00:00', '')"
    )
    conn.commit()
    conn.close()
    fetch = _make_fake_history({"AAPL": {date_cls(2026, 4, 15): 110.0}})
    results = backfill_all_users(
        str(p),
        today=date_cls(2026, 4, 15),
        fetch_history=fetch,
    )
    assert len(results) == 1
    assert results[0]["user_id"] is None
    assert results[0]["backfilled"] == 1


def test_backfill_all_users_multi_tenant(multi_tenant_db_path):
    """Per-user iteration writes per-user snapshots on non-overlapping dates.

    The existing schema's ``PRIMARY KEY (date)`` means any single date can
    only hold one user's row. We exercise per-user isolation by giving each
    user a disjoint date window (alice up to 2026-04-14, bob from 2026-04-15
    onwards) and calling the per-user entry point directly — that's the
    behavior in production today.
    """
    from stock_trading_system.auth.repository import UserRepository
    conn = sqlite3.connect(multi_tenant_db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT,
            password_reset_token TEXT,
            password_reset_expires_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    repo = UserRepository(multi_tenant_db_path)
    repo.create("alice@x.com", "Pass1234!")  # id=1
    repo.create("bob@x.com", "Pass1234!")    # id=2

    from stock_trading_system.migrations.backfill_daily_snapshots import backfill_user
    fetch = _make_fake_history({
        "NVDA": {date_cls(2026, 4, 14): 510.0},
        "TSLA": {date_cls(2026, 4, 15): 220.0},
    })
    r1 = backfill_user(
        multi_tenant_db_path, 1,
        today=date_cls(2026, 4, 14),
        fetch_history=fetch,
    )
    r2 = backfill_user(
        multi_tenant_db_path, 2,
        today=date_cls(2026, 4, 15),
        fetch_history=fetch,
    )
    assert r1["backfilled"] >= 1
    assert r2["backfilled"] >= 1

    conn = sqlite3.connect(multi_tenant_db_path)
    alice_row = conn.execute(
        "SELECT total_value FROM daily_snapshots WHERE user_id = 1 AND date = '2026-04-14'"
    ).fetchone()
    bob_row = conn.execute(
        "SELECT total_value FROM daily_snapshots WHERE user_id = 2 AND date = '2026-04-15'"
    ).fetchone()
    conn.close()
    # alice: 4 NVDA * 510 = 2040
    assert alice_row is not None and alice_row[0] == pytest.approx(2040.0)
    # bob:   2 TSLA * 220 = 440
    assert bob_row is not None and bob_row[0] == pytest.approx(440.0)


def test_progress_callback_invoked(db_path):
    """Worker integration: progress_cb fires per processed day."""
    fetch = _make_fake_history({
        "AAPL": {date_cls(2026, 4, 15): 152.0, date_cls(2026, 4, 16): 153.0},
        "MSFT": {date_cls(2026, 4, 15): 351.0, date_cls(2026, 4, 16): 352.0},
    })
    seen: list[tuple[float, str]] = []
    backfill_user(
        db_path, None,
        today=date_cls(2026, 4, 16),
        fetch_history=fetch,
        progress_cb=lambda pct, msg: seen.append((pct, msg)),
    )
    assert seen, "expected progress_cb to be called"
    # All percentages monotonically increase
    pcts = [s[0] for s in seen]
    assert pcts == sorted(pcts)
    assert pcts[-1] <= 99.0
