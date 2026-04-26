"""SQLite database operations for portfolio management."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from stock_trading_system.portfolio.models import Position, Transaction, DailySnapshot
from stock_trading_system.utils import get_logger

logger = get_logger("portfolio.db")


def _coerce_float(v):
    """Best-effort float conversion that tolerates None / strings / percent suffix."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().rstrip("%").replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


class PortfolioDatabase:
    """SQLite database for portfolio data."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    shares REAL NOT NULL,
                    avg_cost REAL NOT NULL,
                    added_date TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    date TEXT PRIMARY KEY,
                    total_value REAL NOT NULL,
                    total_cost REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    positions_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    created TEXT NOT NULL,
                    triggered INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    market_report TEXT,
                    sentiment_report TEXT,
                    news_report TEXT,
                    fundamentals_report TEXT,
                    investment_debate TEXT,
                    risk_assessment TEXT,
                    trade_decision TEXT,
                    advice_json TEXT,
                    created_at TEXT NOT NULL,
                    action TEXT,
                    confidence TEXT,
                    position_pct REAL,
                    entry_low REAL,
                    entry_high REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    model TEXT,
                    steps_json TEXT
                );

                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER,
                    ticker TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    current_price REAL,
                    triggered_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_scorecards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    price_at_call REAL,
                    return_5d REAL,
                    hit_5d INTEGER,
                    return_20d REAL,
                    hit_20d INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sc_agent_date
                    ON agent_scorecards(agent_id, date DESC);
                CREATE INDEX IF NOT EXISTS idx_sc_backfill
                    ON agent_scorecards(date)
                    WHERE return_5d IS NULL AND price_at_call IS NOT NULL;

                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    prompt_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    reasoning TEXT,
                    status TEXT DEFAULT 'candidate',
                    ab_session_id INTEGER,
                    baseline_session_id INTEGER,
                    sharpe_before REAL,
                    sharpe_after REAL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pv_agent_status
                    ON prompt_versions(agent_id, status);

                CREATE INDEX IF NOT EXISTS idx_analysis_ticker_time
                    ON analysis_history(ticker, created_at DESC);
            """)
            self._migrate_analysis_history(conn)

    def _migrate_analysis_history(self, conn: sqlite3.Connection):
        """Idempotently add structured columns to pre-existing analysis_history."""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_history)").fetchall()}
        additions = [
            ("action", "TEXT"),
            ("confidence", "TEXT"),
            ("position_pct", "REAL"),
            ("entry_low", "REAL"),
            ("entry_high", "REAL"),
            ("stop_loss", "REAL"),
            ("take_profit", "REAL"),
            ("model", "TEXT"),
            ("steps_json", "TEXT"),
        ]
        for name, typ in additions:
            if name not in cols:
                try:
                    conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {name} {typ}")
                except sqlite3.OperationalError as e:
                    logger.warning("Migration for column %s failed: %s", name, e)
        # Backfill structured columns from any existing rows' advice_json.
        try:
            rows = conn.execute(
                "SELECT id, advice_json FROM analysis_history WHERE action IS NULL AND advice_json IS NOT NULL AND advice_json != ''"
            ).fetchall()
            for r in rows:
                try:
                    adv = json.loads(r["advice_json"])
                except Exception:
                    continue
                if not isinstance(adv, dict):
                    continue
                conn.execute(
                    """UPDATE analysis_history SET
                         action = ?, confidence = ?, position_pct = ?,
                         entry_low = ?, entry_high = ?, stop_loss = ?, take_profit = ?
                       WHERE id = ?""",
                    (
                        adv.get("action"),
                        adv.get("confidence"),
                        _coerce_float(adv.get("suggested_position_pct")),
                        _coerce_float(adv.get("entry_price_low")),
                        _coerce_float(adv.get("entry_price_high")),
                        _coerce_float(adv.get("stop_loss")),
                        _coerce_float(adv.get("take_profit")),
                        r["id"],
                    ),
                )
        except sqlite3.OperationalError as e:
            logger.warning("Backfill of analysis_history failed: %s", e)

    # ── Positions ────────────────────────────────────────────────────────

    def get_position(self, ticker: str, user_id: int | None = None) -> Position | None:
        with self._get_conn() as conn:
            if user_id is not None:
                row = conn.execute(
                    "SELECT * FROM positions WHERE ticker = ? AND user_id = ?", (ticker, user_id)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
            if row:
                return Position(**dict(row))
        return None

    def get_all_positions(self, user_id: int | None = None) -> list[Position]:
        with self._get_conn() as conn:
            if user_id is not None:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE user_id = ? ORDER BY ticker", (user_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
            return [Position(**dict(r)) for r in rows]

    def upsert_position(self, position: Position):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO positions (user_id, ticker, market, shares, avg_cost, added_date)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, ticker) DO UPDATE SET
                     shares = excluded.shares,
                     avg_cost = excluded.avg_cost""",
                (position.user_id, position.ticker, position.market,
                 position.shares, position.avg_cost, position.added_date),
            )

    def delete_position(self, ticker: str, user_id: int | None = None):
        with self._get_conn() as conn:
            if user_id is not None:
                conn.execute("DELETE FROM positions WHERE ticker = ? AND user_id = ?", (ticker, user_id))
            else:
                conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))

    # ── Transactions ─────────────────────────────────────────────────────

    def add_transaction(self, txn: Transaction):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO transactions (ticker, action, shares, price, timestamp, notes, user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (txn.ticker, txn.action, txn.shares, txn.price, txn.timestamp, txn.notes, txn.user_id),
            )

    def get_transactions(self, ticker: str | None = None, user_id: int | None = None) -> list[Transaction]:
        with self._get_conn() as conn:
            clauses, params = [], []
            if ticker:
                clauses.append("ticker = ?")
                params.append(ticker)
            if user_id is not None:
                clauses.append("user_id = ?")
                params.append(user_id)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM transactions{where} ORDER BY timestamp DESC", params
            ).fetchall()
            return [Transaction(**dict(r)) for r in rows]

    # ── Snapshots ────────────────────────────────────────────────────────

    def save_snapshot(self, snapshot: DailySnapshot):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO daily_snapshots (date, total_value, total_cost, pnl, pnl_pct, positions_json, user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     total_value = excluded.total_value,
                     total_cost = excluded.total_cost,
                     pnl = excluded.pnl,
                     pnl_pct = excluded.pnl_pct,
                     positions_json = excluded.positions_json""",
                (snapshot.date, snapshot.total_value, snapshot.total_cost,
                 snapshot.pnl, snapshot.pnl_pct, snapshot.positions_json, snapshot.user_id),
            )

    def get_snapshots(
        self,
        days: int | None = 30,
        user_id: int | None = None,
    ) -> list[DailySnapshot]:
        """Return snapshots ordered ascending (oldest → newest) for charting.

        ``days=None`` returns the full series so the dashboard equity curve
        can render every snapshot since the user's first day. A positive
        integer restricts to that rolling window (today minus N days).
        """
        from datetime import date as _date, timedelta as _td

        clauses: list[str] = []
        params: list = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if days is not None:
            cutoff = (_date.today() - _td(days=int(days))).strftime("%Y-%m-%d")
            clauses.append("date >= ?")
            params.append(cutoff)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM daily_snapshots {where} ORDER BY date ASC",
                params,
            ).fetchall()
            return [DailySnapshot(**dict(r)) for r in rows]

    # ── Alerts ───────────────────────────────────────────────────────────

    def add_alert(self, ticker: str, condition: str, threshold: float, user_id: int | None = None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO alerts (ticker, condition, threshold, created, user_id) VALUES (?, ?, ?, ?, ?)",
                (ticker, condition, threshold, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
            )

    def get_active_alerts(self, user_id: int | None = None) -> list[dict]:
        with self._get_conn() as conn:
            if user_id is not None:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE triggered = 0 AND user_id = ? ORDER BY created DESC",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE triggered = 0 ORDER BY created DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def trigger_alert(self, alert_id: int):
        with self._get_conn() as conn:
            conn.execute("UPDATE alerts SET triggered = 1 WHERE id = ?", (alert_id,))

    def remove_alert(self, alert_id: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))

    def save_alert_trigger(self, alert_id: int, ticker: str, condition: str,
                           threshold: float, current_price: float | None = None):
        from datetime import datetime
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO alert_history (alert_id, ticker, condition, threshold, current_price, triggered_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (alert_id, ticker, condition, threshold, current_price,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    def get_alert_history(self, ticker: str | None = None, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM alert_history WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_history ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Analysis History ────────────────────────────────────────────────

    def save_analysis(self, data: dict) -> int:
        """Insert an analysis record. Returns the new row id.

        Structured fields (action/confidence/entry_low/high/stop_loss/take_profit/
        position_pct) are extracted from `advice_json` automatically so downstream
        history comparison queries don't need to re-parse JSON.
        """
        adv = {}
        advice_raw = data.get("advice_json") or ""
        if advice_raw:
            try:
                adv = json.loads(advice_raw) or {}
            except Exception:
                adv = {}
        steps_raw = data.get("steps_json") or ""
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO analysis_history
                   (ticker, date, signal, market_report, sentiment_report,
                    news_report, fundamentals_report, investment_debate,
                    risk_assessment, trade_decision, advice_json, created_at,
                    action, confidence, position_pct,
                    entry_low, entry_high, stop_loss, take_profit, model, steps_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["ticker"], data["date"], data["signal"],
                    data.get("market_report", ""),
                    data.get("sentiment_report", ""),
                    data.get("news_report", ""),
                    data.get("fundamentals_report", ""),
                    data.get("investment_debate", ""),
                    data.get("risk_assessment", ""),
                    data.get("trade_decision", ""),
                    advice_raw,
                    data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    adv.get("action"),
                    adv.get("confidence"),
                    _coerce_float(adv.get("suggested_position_pct")),
                    _coerce_float(adv.get("entry_price_low")),
                    _coerce_float(adv.get("entry_price_high")),
                    _coerce_float(adv.get("stop_loss")),
                    _coerce_float(adv.get("take_profit")),
                    data.get("model"),
                    steps_raw,
                ),
            )
            return int(cur.lastrowid)

    def get_analysis_history(self, ticker: str | None = None, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM analysis_history WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_history ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_analysis_by_id(self, analysis_id: int) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_history WHERE id = ?", (analysis_id,)
            ).fetchone()
            return dict(row) if row else None

    # Columns returned by compare/timeline queries — keep heavy report text out
    # so the comparison payload stays small and mobile-friendly.
    _STRUCTURED_COLS = (
        "id, ticker, date, signal, created_at, action, confidence, position_pct, "
        "entry_low, entry_high, stop_loss, take_profit, model"
    )

    def get_analyses_by_ids(self, analysis_ids: list[int]) -> list[dict]:
        """Return structured (no report bodies) rows for the given ids, ordered
        by created_at ascending so UI can render left-to-right chronologically."""
        if not analysis_ids:
            return []
        # Sanitize to ints to build a safe IN-clause.
        safe_ids = [int(i) for i in analysis_ids]
        placeholders = ",".join("?" * len(safe_ids))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT {self._STRUCTURED_COLS} FROM analysis_history "
                f"WHERE id IN ({placeholders}) ORDER BY created_at ASC",
                safe_ids,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_analysis_timeline(self, ticker: str, limit: int = 20) -> list[dict]:
        """Return up to `limit` most-recent records for one ticker, ordered
        chronologically (oldest → newest) so the UI can draw time on the x-axis.
        """
        with self._get_conn() as conn:
            # Pull the newest N first (DESC + id DESC as stable tie-breaker)...
            rows = conn.execute(
                f"SELECT {self._STRUCTURED_COLS} FROM analysis_history "
                f"WHERE ticker = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
            # ...then flip to ascending for display.
            return [dict(r) for r in rows[::-1]]

    def delete_analysis(self, analysis_id: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM analysis_history WHERE id = ?", (analysis_id,))
            return cur.rowcount > 0
