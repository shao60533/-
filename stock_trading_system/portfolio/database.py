"""SQLite database operations for portfolio management."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from stock_trading_system.portfolio.models import Position, Transaction, DailySnapshot
from stock_trading_system.utils import get_logger

logger = get_logger("portfolio.db")


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
                    created_at TEXT NOT NULL
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
            """)

    # ── Positions ────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Position | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM positions WHERE ticker = ?", (ticker,)).fetchone()
            if row:
                return Position(**dict(row))
        return None

    def get_all_positions(self) -> list[Position]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
            return [Position(**dict(r)) for r in rows]

    def upsert_position(self, position: Position):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO positions (ticker, market, shares, avg_cost, added_date)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(ticker) DO UPDATE SET
                     shares = excluded.shares,
                     avg_cost = excluded.avg_cost""",
                (position.ticker, position.market, position.shares, position.avg_cost, position.added_date),
            )

    def delete_position(self, ticker: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))

    # ── Transactions ─────────────────────────────────────────────────────

    def add_transaction(self, txn: Transaction):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO transactions (ticker, action, shares, price, timestamp, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (txn.ticker, txn.action, txn.shares, txn.price, txn.timestamp, txn.notes),
            )

    def get_transactions(self, ticker: str | None = None) -> list[Transaction]:
        with self._get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE ticker = ? ORDER BY timestamp DESC", (ticker,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM transactions ORDER BY timestamp DESC"
                ).fetchall()
            return [Transaction(**dict(r)) for r in rows]

    # ── Snapshots ────────────────────────────────────────────────────────

    def save_snapshot(self, snapshot: DailySnapshot):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO daily_snapshots (date, total_value, total_cost, pnl, pnl_pct, positions_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     total_value = excluded.total_value,
                     total_cost = excluded.total_cost,
                     pnl = excluded.pnl,
                     pnl_pct = excluded.pnl_pct,
                     positions_json = excluded.positions_json""",
                (snapshot.date, snapshot.total_value, snapshot.total_cost,
                 snapshot.pnl, snapshot.pnl_pct, snapshot.positions_json),
            )

    def get_snapshots(self, days: int = 30) -> list[DailySnapshot]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_snapshots ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
            return [DailySnapshot(**dict(r)) for r in rows]

    # ── Alerts ───────────────────────────────────────────────────────────

    def add_alert(self, ticker: str, condition: str, threshold: float):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO alerts (ticker, condition, threshold, created) VALUES (?, ?, ?, ?)",
                (ticker, condition, threshold, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    def get_active_alerts(self) -> list[dict]:
        with self._get_conn() as conn:
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
        """Insert one analysis_history row. Returns the new row id."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO analysis_history
                   (ticker, date, signal, market_report, sentiment_report,
                    news_report, fundamentals_report, investment_debate,
                    risk_assessment, trade_decision, advice_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["ticker"], data["date"], data["signal"],
                    data.get("market_report", ""),
                    data.get("sentiment_report", ""),
                    data.get("news_report", ""),
                    data.get("fundamentals_report", ""),
                    data.get("investment_debate", ""),
                    data.get("risk_assessment", ""),
                    data.get("trade_decision", ""),
                    data.get("advice_json", ""),
                    data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
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
