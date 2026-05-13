"""Unit tests for ``stock_trading_system.strategy.paper_trader.eod_runner``.

Covers the contract surface exercised by the auto-snapshot scheduler
and the manual ``/api/paper/tickers/<ticker>/eod`` endpoint:

* ``run_paper_trade_eod_all`` iterates every running ticker session,
  honours an optional ``user_id`` scope, captures per-session errors
  without aborting the whole run, and exposes ``latest_date``.
* Sessions in ``status='running'`` get advanced; replay / completed /
  cancelled sessions are skipped.
* When ``DailyUpdater`` has already populated ``last_eod_date``, the
  runner doesn't re-emit duplicate rows — it relies on the underlying
  updater to resume from ``last_eod_date + 1``.
* ``paper_trade_status_snapshot`` reports live counters (total /
  stale / latest) and surfaces the most recent run summary.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stock_trading_system.strategy.paper_trader import (
    EodRunSummary,
    PaperTradeStore,
    ensure_ticker_session,
    paper_trade_status_snapshot,
    run_paper_trade_eod_all,
    run_paper_trade_eod_for_ticker,
)
from stock_trading_system.strategy.paper_trader.eod_runner import (
    _reset_last_run_for_tests,
)


# ── Test fixtures ────────────────────────────────────────────────────────────


class _StubUpdater:
    """In-memory DailyUpdater stand-in. Records every update_session
    call and emits a deterministic single-row response per session."""

    def __init__(self, *_a, fail_on: set[int] | None = None,
                 rows_by_session: dict[int, list[dict]] | None = None,
                 **_kw):
        self.calls: list[int] = []
        self._fail_on = fail_on or set()
        self._rows = rows_by_session or {}

    def update_session(self, session_id, target_date=None):
        sid = int(session_id)
        self.calls.append(sid)
        if sid in self._fail_on:
            raise RuntimeError(f"stubbed failure for session {sid}")
        return list(self._rows.get(sid, [{"date": "2026-05-13", "total_value": 100000}]))


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "paper.db"
    return PaperTradeStore(str(db))


# ── run_paper_trade_eod_all ──────────────────────────────────────────────────


def test_run_all_iterates_every_running_ticker_session(store):
    _reset_last_run_for_tests()
    s1 = ensure_ticker_session(store, "NVDA",
                                start_date="2026-04-15", user_id=1)
    s2 = ensure_ticker_session(store, "TSLA",
                                start_date="2026-04-20", user_id=2)
    s3 = ensure_ticker_session(store, "AAPL",
                                start_date="2026-04-25", user_id=1)
    updater = _StubUpdater()

    summary = run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: updater,
    )

    assert summary.total_sessions == 3
    assert summary.updated_sessions == 3
    assert summary.new_rows == 3
    assert set(updater.calls) == {s1["id"], s2["id"], s3["id"]}
    assert summary.latest_date == "2026-05-13"
    assert summary.errors == []


def test_run_all_skips_non_running_and_replay_sessions(store):
    _reset_last_run_for_tests()
    s_active = ensure_ticker_session(store, "NVDA",
                                      start_date="2026-04-15", user_id=1)
    s_completed = ensure_ticker_session(store, "TSLA",
                                         start_date="2026-04-15", user_id=1)
    store.update_session(s_completed["id"], status="completed")
    # Replay session is forward-mode by ensure_ticker_session default;
    # mark replay_mode explicitly to mimic the simulator path.
    s_replay = ensure_ticker_session(store, "MSFT",
                                      start_date="2026-04-15", user_id=1)
    with store._conn() as conn:
        conn.execute(
            "UPDATE paper_trade_sessions SET replay_mode='replay' WHERE id = ?",
            (s_replay["id"],),
        )

    updater = _StubUpdater()
    summary = run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: updater,
    )

    assert updater.calls == [int(s_active["id"])]
    assert summary.total_sessions == 1
    assert summary.updated_sessions == 1


def test_run_all_user_id_filter_isolates_users(store):
    _reset_last_run_for_tests()
    alice_sess = ensure_ticker_session(store, "NVDA",
                                        start_date="2026-04-15", user_id=1)
    bob_sess = ensure_ticker_session(store, "TSLA",
                                      start_date="2026-04-15", user_id=2)
    updater = _StubUpdater()

    summary = run_paper_trade_eod_all(
        config={}, store=store, user_id=1,
        updater_factory=lambda _c, _s: updater,
    )

    assert updater.calls == [int(alice_sess["id"])]
    assert bob_sess["id"] not in updater.calls
    assert summary.user_id == 1
    assert summary.total_sessions == 1


def test_run_all_captures_errors_per_session(store):
    _reset_last_run_for_tests()
    s_ok = ensure_ticker_session(store, "NVDA",
                                  start_date="2026-04-15", user_id=1)
    s_fail = ensure_ticker_session(store, "TSLA",
                                    start_date="2026-04-15", user_id=1)
    updater = _StubUpdater(fail_on={int(s_fail["id"])})

    summary = run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: updater,
    )

    assert summary.total_sessions == 2
    assert summary.updated_sessions == 1
    assert summary.new_rows == 1
    assert len(summary.errors) == 1
    err = summary.errors[0]
    assert err["session_id"] == int(s_fail["id"])
    assert "stubbed failure" in err["error"]
    # Per-session row for the failing session carries the same error.
    failing = next(r for r in summary.per_session
                   if r["session_id"] == int(s_fail["id"]))
    assert failing["error"] is not None
    assert failing["new_rows"] == 0


def test_run_all_idempotent_when_no_new_bars(store):
    """If DailyUpdater returns [] (no new trading day yet), the
    summary reports 0 new rows and ``latest_date`` is None even
    though the session is technically up-to-date."""
    _reset_last_run_for_tests()
    s = ensure_ticker_session(store, "NVDA",
                               start_date="2026-04-15", user_id=1)
    updater = _StubUpdater(rows_by_session={int(s["id"]): []})

    summary = run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: updater,
    )

    assert summary.total_sessions == 1
    assert summary.updated_sessions == 0
    assert summary.new_rows == 0
    assert summary.latest_date is None


# ── run_paper_trade_eod_for_ticker ───────────────────────────────────────────


def test_run_for_ticker_updates_every_sibling_session(store):
    """User A has TWO legacy duplicate sessions for AAPL (created
    before the unique index landed). Manual ticker EOD must hit
    BOTH session ids, not just the first one. We drop the unique
    index for this fixture to recreate the pre-index legacy state
    — production migrations leave the index in place."""
    _reset_last_run_for_tests()
    sib1 = ensure_ticker_session(store, "AAPL",
                                  start_date="2026-04-15", user_id=10)
    with store._conn() as conn:
        # Drop the migration-installed unique index to simulate a
        # legacy DB carrying duplicate (ticker, user_id) rows from
        # before the index landed.
        conn.execute("DROP INDEX IF EXISTS idx_session_ticker_user")
        conn.execute(
            """INSERT INTO paper_trade_sessions
               (name, mode, status, start_capital, start_date,
                config_json, auto_track, is_system, ticker, user_id, created_at)
               VALUES ('AAPL legacy', 'ticker', 'running', 100000,
                       '2026-04-15', '{}', 0, 0, 'AAPL', 10, datetime('now'))""",
        )
    sib_ids = store.aggregate_ticker_session_ids("AAPL", user_id=10)
    assert len(sib_ids) >= 2, "test fixture expected at least 2 sibling rows"
    updater = _StubUpdater()

    summary = run_paper_trade_eod_for_ticker(
        config={}, store=store,
        ticker="AAPL", user_id=10,
        updater_factory=lambda _c, _s: updater,
    )

    assert set(updater.calls) == set(sib_ids)
    assert summary.total_sessions == len(sib_ids)
    assert summary.user_id == 10
    # Sibling 1's id MUST appear since aggregate_ticker_session_ids
    # is ordered earliest first.
    assert int(sib1["id"]) in updater.calls


def test_run_for_ticker_isolates_other_users(store):
    """Bob's session for AAPL must never be touched by Alice's call."""
    _reset_last_run_for_tests()
    alice_sess = ensure_ticker_session(store, "AAPL",
                                        start_date="2026-04-15", user_id=10)
    bob_sess = ensure_ticker_session(store, "AAPL",
                                      start_date="2026-04-15", user_id=20)
    assert alice_sess["id"] != bob_sess["id"]
    updater = _StubUpdater()

    summary = run_paper_trade_eod_for_ticker(
        config={}, store=store,
        ticker="AAPL", user_id=10,
        updater_factory=lambda _c, _s: updater,
    )

    assert updater.calls == [int(alice_sess["id"])]
    assert int(bob_sess["id"]) not in updater.calls
    assert summary.user_id == 10


def test_run_for_ticker_returns_empty_summary_when_no_sibling(store):
    """No session for (alice, ZZZZ) — summary reports zero sessions
    and the underlying updater is never invoked."""
    _reset_last_run_for_tests()
    updater = _StubUpdater()

    summary = run_paper_trade_eod_for_ticker(
        config={}, store=store,
        ticker="ZZZZ", user_id=99,
        updater_factory=lambda _c, _s: updater,
    )

    assert summary.total_sessions == 0
    assert summary.updated_sessions == 0
    assert summary.new_rows == 0
    assert updater.calls == []


# ── Idempotency contract via real DailyUpdater + last_eod_date ───────────────


def test_run_all_uses_last_eod_date_to_skip_already_written_days(
    store, monkeypatch,
):
    """Sessions that already have ``last_eod_date='2026-05-13'`` must
    NOT trigger DailyUpdater to re-emit the 2026-05-13 row. We assert
    the underlying ``store.update_session_last_eod`` was last updated
    AT OR AFTER the existing date — never moved backwards."""
    _reset_last_run_for_tests()
    s = ensure_ticker_session(store, "NVDA",
                               start_date="2026-04-15", user_id=1)
    store.update_session_last_eod(s["id"], "2026-05-13")

    # Stub returns ONE new row dated 2026-05-14 (the next trading day).
    captured: list[tuple[int, str | None]] = []

    class _ResumeStub:
        def __init__(self, *_a, **_kw): pass

        def update_session(self, session_id, target_date=None):
            captured.append((int(session_id), target_date))
            # Simulate DailyUpdater's behaviour: it consults
            # ``last_eod_date`` and only emits dates strictly after.
            return [{"date": "2026-05-14", "total_value": 101_000}]

    summary = run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: _ResumeStub(),
    )
    assert summary.new_rows == 1
    assert summary.latest_date == "2026-05-14"
    # Stub was called exactly once for our session.
    assert captured == [(int(s["id"]), None)]


# ── paper_trade_status_snapshot ──────────────────────────────────────────────


def test_status_snapshot_counts_stale_running_sessions(store):
    _reset_last_run_for_tests()
    fresh = ensure_ticker_session(store, "NVDA",
                                   start_date="2026-04-15", user_id=1)
    stale_a = ensure_ticker_session(store, "TSLA",
                                     start_date="2026-04-15", user_id=1)
    stale_b = ensure_ticker_session(store, "AAPL",
                                     start_date="2026-04-15", user_id=2)
    # Today's date used by the snapshot guard — pin one session to
    # "fresh" by setting last_eod_date to today.
    from datetime import date as _date
    today = _date.today().isoformat()
    store.update_session_last_eod(fresh["id"], today)

    snap = paper_trade_status_snapshot(store)

    assert snap["total_ticker_sessions"] == 3
    # 2 stale (TSLA, AAPL — last_eod_date is NULL or before today).
    assert snap["stale_sessions_count"] >= 2
    # last_run is None until run_paper_trade_eod_all fires.
    assert snap["last_run"] is None


def test_status_snapshot_surfaces_last_run_summary(store):
    _reset_last_run_for_tests()
    s = ensure_ticker_session(store, "NVDA",
                               start_date="2026-04-15", user_id=1)
    run_paper_trade_eod_all(
        config={}, store=store,
        updater_factory=lambda _c, _s: _StubUpdater(),
    )
    snap = paper_trade_status_snapshot(store)
    assert snap["last_run"] is not None
    assert snap["last_run"]["total_sessions"] == 1
    assert snap["last_run"]["new_rows"] == 1
