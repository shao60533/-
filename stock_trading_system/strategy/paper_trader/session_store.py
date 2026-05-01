"""SQLite persistence for paper-trade sessions, trades, equity, and tracking.

Tables owned by this module (created on-demand, idempotent):
  - paper_trade_sessions  — one row per simulation run / live tracker
  - paper_trade_trades    — individual buy→sell round trips
  - paper_trade_equity    — daily portfolio value snapshots
  - analysis_tracked      — audit trail linking analyses to sessions

A built-in default session (id=1, is_system=1) is ensured on every
get/init call so the auto-track hook always has a target.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.store")


# ── Schema ─────────────────────────────────────────────────────────────────

_SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS paper_trade_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,                       -- replay | live | ticker
    status TEXT NOT NULL,                     -- pending | running | completed | failed | cancelled
    task_id TEXT,
    start_capital REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    config_json TEXT NOT NULL,
    auto_track INTEGER DEFAULT 0,             -- 1 if this session auto-absorbs new analyses
    is_system INTEGER DEFAULT 0,              -- 1 for built-in default session (non-deletable)
    ticker TEXT,                              -- V2: per-ticker session (NULL = legacy multi-ticker)
    last_eod_date TEXT,                       -- V2: last daily_stats written
    metrics_json TEXT,
    benchmark_metrics_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""

_SCHEMA_STRATEGY_EVENTS = """
CREATE TABLE IF NOT EXISTS paper_trade_strategy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    analysis_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    prev_signal TEXT,
    new_signal TEXT NOT NULL,
    advice_action TEXT,
    action TEXT NOT NULL,                     -- open|add|reduce|close|reverse|hold|skipped|no_action
    shares_delta REAL DEFAULT 0,
    price REAL,
    trade_id INTEGER,
    confidence REAL,
    target_position_pct REAL,
    entry_low REAL,
    entry_high REAL,
    stop_loss REAL,
    take_profit REAL,
    reasoning TEXT,
    skip_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_TRADING_PLANS = """
CREATE TABLE IF NOT EXISTS paper_trade_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    analysis_id INTEGER NOT NULL,
    rating TEXT,
    thesis TEXT,
    holding_months_min INTEGER,
    holding_months_max INTEGER,
    raw_summary TEXT,
    plan_json TEXT NOT NULL,
    parse_method TEXT,
    status TEXT DEFAULT 'active',         -- active | superseded | expired
    superseded_by_plan_id INTEGER,
    superseded_at TEXT,
    fingerprint TEXT,                     -- v1.3 F1 dedup
    reconfirmed_count INTEGER DEFAULT 1,  -- v1.3 F1 dedup
    reconfirmed_at TEXT,                  -- v1.3 F1 dedup
    analysis_ids TEXT,                    -- v1.3 F1 dedup (json array)
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_PLANNED_ORDERS = """
CREATE TABLE IF NOT EXISTS paper_trade_planned_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    order_type TEXT NOT NULL,             -- entry_initial | entry_add | exit_stop | exit_target | exit_trailing
    sequence INTEGER NOT NULL,
    pct_target_total REAL,
    trigger_kind TEXT NOT NULL,           -- immediate | price_above | price_below | breakout_retest | trailing_ma | time_stop
    trigger_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',        -- pending | triggered | cancelled | superseded
    triggered_date TEXT,
    triggered_price REAL,
    trade_id INTEGER,
    description TEXT,
    superseded_by_plan_id INTEGER,
    superseded_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES paper_trade_plans(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_DAILY_STATS = """
CREATE TABLE IF NOT EXISTS paper_trade_daily_stats (
    session_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    position_shares REAL DEFAULT 0,
    avg_cost REAL,
    position_value REAL DEFAULT 0,
    cash REAL NOT NULL,
    total_value REAL NOT NULL,
    daily_pnl REAL DEFAULT 0,
    daily_pnl_pct REAL DEFAULT 0,
    cum_pnl REAL DEFAULT 0,
    cum_pnl_pct REAL DEFAULT 0,
    drawdown_pct REAL DEFAULT 0,
    active_signal TEXT,
    active_analysis_id INTEGER,
    days_held INTEGER DEFAULT 0,
    strategy_changed INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, date),
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_TRADES = """
CREATE TABLE IF NOT EXISTS paper_trade_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    entry_analysis_id INTEGER,
    exit_analysis_id INTEGER,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,                         -- stop | target | reverse_signal | time_stop | session_end
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_EQUITY = """
CREATE TABLE IF NOT EXISTS paper_trade_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    benchmark_value REAL,
    open_positions INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_SCHEMA_TRACKED = """
CREATE TABLE IF NOT EXISTS analysis_tracked (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    session_id INTEGER NOT NULL,
    tracked_at TEXT NOT NULL,
    tracked_by TEXT DEFAULT 'auto',           -- auto | user
    status TEXT DEFAULT 'pending',            -- pending | executed | skipped | no_action | failed
    executed_trade_id INTEGER,
    skip_reason TEXT,
    notes TEXT,
    FOREIGN KEY (session_id) REFERENCES paper_trade_sessions(id) ON DELETE CASCADE
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_paper_sessions_created ON paper_trade_sessions(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_session ON paper_trade_trades(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker ON paper_trade_trades(ticker, entry_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_paper_equity_session_date ON paper_trade_equity(session_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_tracked_analysis ON analysis_tracked(analysis_id)",
    "CREATE INDEX IF NOT EXISTS idx_tracked_ticker ON analysis_tracked(ticker, tracked_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tracked_session ON analysis_tracked(session_id, status)",
]


# Default session config (v1.2: auto-track every non-ERROR analysis)
_DEFAULT_SESSION_CONFIG = {
    "filters": {
        "signals": ["BUY", "OVERWEIGHT", "SELL", "UNDERWEIGHT", "HOLD"],
        "tickers": None,
        "markets": ["us", "cn"],
    },
    "sizing": {"mode": "advice", "max_single_pct": 20, "fixed_pct": 10},
    "exit_rules": {
        "use_advice_stop": True,
        "use_advice_target": True,
        "time_stop_days": 90,
        "follow_reverse_signal": True,
    },
    "cost": {"commission_bps": 0, "slippage_bps": 5},
    "benchmark": "SPY",
}


# ── Store class ────────────────────────────────────────────────────────────

class PaperTradeStore:
    """Thread-safe SQLite store for paper-trade data."""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self.ensure_default_session()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._lock, self._conn() as conn:
            conn.execute(_SCHEMA_SESSIONS)
            conn.execute(_SCHEMA_TRADES)
            conn.execute(_SCHEMA_EQUITY)
            conn.execute(_SCHEMA_TRACKED)
            conn.execute(_SCHEMA_STRATEGY_EVENTS)
            conn.execute(_SCHEMA_DAILY_STATS)
            conn.execute(_SCHEMA_TRADING_PLANS)
            conn.execute(_SCHEMA_PLANNED_ORDERS)
            # Migrate legacy sessions table (idempotent)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(paper_trade_sessions)")}
            if "ticker" not in cols:
                conn.execute("ALTER TABLE paper_trade_sessions ADD COLUMN ticker TEXT")
            if "last_eod_date" not in cols:
                conn.execute("ALTER TABLE paper_trade_sessions ADD COLUMN last_eod_date TEXT")
            if "user_id" not in cols:
                conn.execute("ALTER TABLE paper_trade_sessions ADD COLUMN user_id INTEGER")
            if "replay_mode" not in cols:
                conn.execute("ALTER TABLE paper_trade_sessions ADD COLUMN replay_mode TEXT")
            # Unique (ticker, user_id) — one forward-tracking session per
            # ticker per user. NULL user_id treated as a distinct legacy slot.
            conn.execute("DROP INDEX IF EXISTS idx_session_ticker")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_session_ticker_user "
                "ON paper_trade_sessions(ticker, IFNULL(user_id, -1)) "
                "WHERE ticker IS NOT NULL AND is_system = 0"
            )
            # v1.3 F1: paper_trade_plans columns (idempotent for legacy DBs)
            plan_cols = {r[1] for r in conn.execute("PRAGMA table_info(paper_trade_plans)")}
            for col, ddl in (
                ("fingerprint",
                 "ALTER TABLE paper_trade_plans ADD COLUMN fingerprint TEXT"),
                ("reconfirmed_count",
                 "ALTER TABLE paper_trade_plans ADD COLUMN reconfirmed_count INTEGER DEFAULT 1"),
                ("reconfirmed_at",
                 "ALTER TABLE paper_trade_plans ADD COLUMN reconfirmed_at TEXT"),
                ("analysis_ids",
                 "ALTER TABLE paper_trade_plans ADD COLUMN analysis_ids TEXT"),
            ):
                if col not in plan_cols:
                    conn.execute(ddl)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_plans_session_ticker_fp "
                "ON paper_trade_plans(session_id, fingerprint)"
            )
            for idx_sql in _INDEXES:
                conn.execute(idx_sql)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_strategy_events_session "
                "ON paper_trade_strategy_events(session_id, event_date DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_strategy_events_analysis "
                "ON paper_trade_strategy_events(analysis_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_session "
                "ON paper_trade_plans(session_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_status "
                "ON paper_trade_plans(session_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_plan "
                "ON paper_trade_planned_orders(plan_id, sequence)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_pending "
                "ON paper_trade_planned_orders(session_id, status)"
            )
        logger.info("paper_trader schema initialized at %s", self._db_path)

    # ── Default session ────────────────────────────────────────────────

    def ensure_default_session(self) -> int:
        """Create the built-in default session if missing. Returns its id."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM paper_trade_sessions WHERE is_system=1 LIMIT 1"
            ).fetchone()
            if row:
                return int(row["id"])

            now = _now_iso()
            today = datetime.now().strftime("%Y-%m-%d")
            cur = conn.execute(
                """INSERT INTO paper_trade_sessions
                   (name, mode, status, start_capital, start_date, end_date,
                    config_json, auto_track, is_system, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "AI 分析自动追踪（默认）",
                    "live",
                    "running",
                    100000.0,
                    today,
                    None,
                    json.dumps(_DEFAULT_SESSION_CONFIG, ensure_ascii=False),
                    1,
                    1,
                    now,
                ),
            )
            sid = cur.lastrowid
            logger.info("Created default paper-trade session id=%s", sid)
            return int(sid)

    def get_default_session_id(self) -> int:
        """Return the default session id (creating if needed)."""
        return self.ensure_default_session()

    # ── Sessions ───────────────────────────────────────────────────────

    def create_session(
        self,
        name: str,
        mode: str,
        start_capital: float,
        start_date: str,
        config: dict,
        end_date: str | None = None,
        auto_track: bool = False,
    ) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trade_sessions
                   (name, mode, status, start_capital, start_date, end_date,
                    config_json, auto_track, is_system, created_at)
                   VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, 0, ?)""",
                (name, mode, start_capital, start_date, end_date,
                 json.dumps(config, ensure_ascii=False),
                 1 if auto_track else 0,
                 _now_iso()),
            )
            return int(cur.lastrowid)

    def get_session(self, session_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trade_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return _row_to_session(row) if row else None

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_sessions
                   ORDER BY is_system DESC, created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def update_session(self, session_id: int, **fields) -> None:
        if not fields:
            return
        allowed = {
            "status", "task_id", "end_date", "metrics_json",
            "benchmark_metrics_json", "completed_at", "auto_track",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("metrics_json", "benchmark_metrics_json") and isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return
        vals.append(session_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE paper_trade_sessions SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    def delete_session(self, session_id: int) -> bool:
        """Delete a session (cascades to trades/equity/tracked). Refuses system sessions."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT is_system FROM paper_trade_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return False
            if row["is_system"]:
                logger.warning("Refusing to delete system session %s", session_id)
                return False
            conn.execute("DELETE FROM paper_trade_sessions WHERE id = ?", (session_id,))
            return True

    def active_auto_track_session_ids(self) -> list[int]:
        """All sessions with auto_track=1 and status in (pending, running)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id FROM paper_trade_sessions
                   WHERE auto_track = 1 AND status IN ('pending', 'running')"""
            ).fetchall()
        return [int(r["id"]) for r in rows]

    # ── Trades ─────────────────────────────────────────────────────────

    def insert_trade(self, trade: dict) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trade_trades
                   (session_id, ticker, entry_analysis_id, entry_date, entry_price,
                    shares, stop_loss, take_profit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade["session_id"], trade["ticker"], trade.get("entry_analysis_id"),
                    trade["entry_date"], trade["entry_price"], trade["shares"],
                    trade.get("stop_loss"), trade.get("take_profit"),
                ),
            )
            return int(cur.lastrowid)

    def close_trade(
        self, trade_id: int, exit_date: str, exit_price: float,
        exit_reason: str, exit_analysis_id: int | None = None,
    ) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT entry_date, entry_price, shares FROM paper_trade_trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if not row:
                return
            entry_price = float(row["entry_price"])
            shares = float(row["shares"])
            pnl = (exit_price - entry_price) * shares
            pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0
            hold_days = _days_between(row["entry_date"], exit_date)
            conn.execute(
                """UPDATE paper_trade_trades
                   SET exit_date = ?, exit_price = ?, exit_reason = ?,
                       exit_analysis_id = ?, pnl = ?, pnl_pct = ?, hold_days = ?
                   WHERE id = ?""",
                (exit_date, exit_price, exit_reason, exit_analysis_id,
                 round(pnl, 2), round(pnl_pct, 2), hold_days, trade_id),
            )

    def list_trades(self, session_id: int, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_trades
                   WHERE session_id = ? ORDER BY entry_date DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def open_positions(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_trades
                   WHERE session_id = ? AND exit_date IS NULL
                   ORDER BY entry_date DESC""",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Equity ─────────────────────────────────────────────────────────

    def insert_equity(
        self, session_id: int, date: str, total_value: float,
        cash: float, positions_value: float,
        benchmark_value: float | None = None, open_positions: int = 0,
    ) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO paper_trade_equity
                   (session_id, date, total_value, cash, positions_value,
                    benchmark_value, open_positions)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, date, total_value, cash, positions_value,
                 benchmark_value, open_positions),
            )

    def list_equity(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT date, total_value, cash, positions_value,
                          benchmark_value, open_positions
                   FROM paper_trade_equity
                   WHERE session_id = ? ORDER BY date""",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Tracking ───────────────────────────────────────────────────────

    def insert_tracked(
        self, analysis_id: int, ticker: str, session_id: int,
        status: str = "pending", tracked_by: str = "auto",
        notes: str | None = None,
    ) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO analysis_tracked
                   (analysis_id, ticker, session_id, tracked_at, tracked_by,
                    status, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (analysis_id, ticker, session_id, _now_iso(), tracked_by,
                 status, notes),
            )
            return int(cur.lastrowid)

    def update_tracked(self, tracked_id: int, **fields) -> None:
        allowed = {"status", "executed_trade_id", "skip_reason", "notes"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return
        vals.append(tracked_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE analysis_tracked SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    def list_tracked_by_ticker(self, ticker: str, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*, a.signal, a.date AS analysis_date,
                          a.advice_json, a.created_at AS analysis_created_at,
                          s.name AS session_name,
                          tr.pnl, tr.pnl_pct, tr.hold_days, tr.exit_reason,
                          tr.entry_price, tr.exit_price
                   FROM analysis_tracked t
                   JOIN analysis_history a ON t.analysis_id = a.id
                   JOIN paper_trade_sessions s ON t.session_id = s.id
                   LEFT JOIN paper_trade_trades tr ON t.executed_trade_id = tr.id
                   WHERE t.ticker = ?
                   ORDER BY t.tracked_at DESC LIMIT ?""",
                (ticker.upper(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_tracked_by_analysis(self, analysis_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*, s.name AS session_name
                   FROM analysis_tracked t
                   JOIN paper_trade_sessions s ON t.session_id = s.id
                   WHERE t.analysis_id = ?
                   ORDER BY t.tracked_at DESC""",
                (analysis_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_tracked_by_session(
        self, session_id: int, status: str | None = None, limit: int = 500,
    ) -> list[dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    """SELECT t.*, a.signal, a.date AS analysis_date, a.advice_json
                       FROM analysis_tracked t
                       JOIN analysis_history a ON t.analysis_id = a.id
                       WHERE t.session_id = ? AND t.status = ?
                       ORDER BY t.tracked_at DESC LIMIT ?""",
                    (session_id, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT t.*, a.signal, a.date AS analysis_date, a.advice_json
                       FROM analysis_tracked t
                       JOIN analysis_history a ON t.analysis_id = a.id
                       WHERE t.session_id = ?
                       ORDER BY t.tracked_at DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_tracked(self, tracked_id: int) -> bool:
        """Only pending tracked records can be cancelled."""
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM analysis_tracked WHERE id = ?",
                (tracked_id,),
            ).fetchone()
            if not row or row["status"] != "pending":
                return False
            conn.execute("DELETE FROM analysis_tracked WHERE id = ?", (tracked_id,))
            return True


# ── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _plan_fingerprint(plan: dict) -> str:
    """SHA1 fingerprint of plan content for dedup (F1)."""
    import hashlib
    orders = plan.get("orders", [])
    payload = json.dumps({
        "entry_low": plan.get("entry_low"),
        "entry_high": plan.get("entry_high"),
        "stop_loss": plan.get("stop_loss"),
        "take_profit": plan.get("take_profit"),
        "rating": plan.get("rating"),
        "tiers": sorted(
            [(o.get("sequence", 0), str(o.get("trigger", {})), o.get("pct_target_total", 0))
             for o in orders]
        ),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


def _days_between(a: str, b: str) -> int:
    try:
        da = datetime.strptime(a.split()[0], "%Y-%m-%d")
        db = datetime.strptime(b.split()[0], "%Y-%m-%d")
        return max(0, (db - da).days)
    except Exception:
        return 0


def _row_to_plan(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("plan_json")
    if raw:
        try:
            d["plan"] = json.loads(raw)
        except Exception:
            d["plan"] = None
    return d


def _row_to_order(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("trigger_json")
    if raw:
        try:
            d["trigger"] = json.loads(raw)
        except Exception:
            d["trigger"] = {}
    return d


def _row_to_session(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("config_json", "metrics_json", "benchmark_metrics_json"):
        raw = d.get(key)
        if raw:
            try:
                d[key.replace("_json", "")] = json.loads(raw)
            except Exception:
                d[key.replace("_json", "")] = None
    d["auto_track"] = bool(d.get("auto_track"))
    d["is_system"] = bool(d.get("is_system"))
    return d


# V2 methods are attached to PaperTradeStore below.

def _v2_methods():
    """Inject V2 methods onto PaperTradeStore (kept here to avoid churn above)."""

    def find_session_by_ticker(self, ticker: str,
                                user_id: int | None = None) -> dict | None:
        """Look up forward-tracking session for ticker.

        ``user_id`` strictly scopes the lookup so two users tracking the
        same ticker get isolated sessions. When ``user_id`` is ``None`` the
        first matching row is returned (preserves legacy display callers
        such as ``/api/paper/tickers/<ticker>`` that don't carry user
        context).
        """
        with self._conn() as conn:
            if user_id is None:
                row = conn.execute(
                    "SELECT * FROM paper_trade_sessions "
                    "WHERE ticker = ? AND is_system = 0 "
                    "ORDER BY user_id IS NULL DESC, created_at DESC LIMIT 1",
                    (ticker.upper(),),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM paper_trade_sessions "
                    "WHERE ticker = ? AND is_system = 0 AND user_id = ? "
                    "LIMIT 1",
                    (ticker.upper(), int(user_id)),
                ).fetchone()
            return _row_to_session(row) if row else None

    def create_ticker_session(
        self, ticker: str, start_date: str,
        start_capital: float = 100000.0, config: dict | None = None,
        user_id: int | None = None,
    ) -> int:
        cfg = config or {
            "sizing": {"mode": "advice", "default_pct": 0.1, "max_single_pct": 0.5},
            "exit_rules": {"use_advice_stop": True, "use_advice_target": True,
                           "default_stop_pct": 0.08, "default_target_pct": 0.20,
                           "max_hold_days": 90, "follow_reverse_signal": True},
            "cost": {"commission_bps": 5, "slippage_bps": 10},
            "benchmark": "SPY",
        }
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trade_sessions
                   (name, mode, status, start_capital, start_date, end_date,
                    config_json, auto_track, is_system, ticker, user_id, created_at)
                   VALUES (?, 'ticker', 'running', ?, ?, NULL, ?, 1, 0, ?, ?, ?)""",
                (f"{ticker.upper()} · 纸面追踪",
                 start_capital, start_date,
                 json.dumps(cfg, ensure_ascii=False),
                 ticker.upper(),
                 int(user_id) if user_id is not None else None,
                 _now_iso()),
            )
            return int(cur.lastrowid)

    def list_ticker_sessions(self, mode: str | None = None) -> list[dict]:
        """Return ticker-scoped sessions enriched with plan/order/position counters.

        ``mode='forward'`` filters out simulator replay rows; ``'replay'``
        filters out forward-tracking rows; ``None`` returns both.
        """
        sql = """
            SELECT s.*,
              (SELECT COUNT(*) FROM paper_trade_plans
                 WHERE session_id = s.id AND status = 'active')           AS active_plan_count,
              (SELECT COUNT(*) FROM paper_trade_planned_orders
                 WHERE session_id = s.id AND status = 'pending')           AS pending_orders_count,
              (SELECT COUNT(*) FROM paper_trade_planned_orders
                 WHERE session_id = s.id AND status = 'triggered')         AS triggered_orders_count,
              (SELECT position_shares FROM paper_trade_daily_stats
                 WHERE session_id = s.id ORDER BY date DESC LIMIT 1)       AS open_position_shares,
              (SELECT skip_reason FROM paper_trade_strategy_events
                 WHERE session_id = s.id
                 ORDER BY event_date DESC, id DESC LIMIT 1)                AS last_skip_reason
            FROM paper_trade_sessions s
            WHERE s.ticker IS NOT NULL AND s.is_system = 0
        """
        if mode == "forward":
            sql += " AND (s.replay_mode IS NULL OR s.replay_mode = '')"
        elif mode == "replay":
            sql += " AND s.replay_mode IS NOT NULL AND s.replay_mode != ''"
        sql += " ORDER BY s.created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        out: list[dict] = []
        for r in rows:
            d = _row_to_session(r)
            for k in ("active_plan_count", "pending_orders_count",
                      "triggered_orders_count", "open_position_shares",
                      "last_skip_reason"):
                d[k] = r[k]
            out.append(d)
        return out

    def update_session_last_eod(self, session_id: int, date: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE paper_trade_sessions SET last_eod_date = ? WHERE id = ?",
                (date, session_id),
            )

    # ── Strategy events ────────────────────────────────────────────────

    def insert_strategy_event(self, **f) -> int:
        required = ("session_id", "analysis_id", "event_date", "new_signal", "action")
        for k in required:
            if f.get(k) is None:
                raise ValueError(f"insert_strategy_event missing {k}")
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trade_strategy_events
                   (session_id, analysis_id, event_date, prev_signal, new_signal,
                    advice_action, action, shares_delta, price, trade_id,
                    confidence, target_position_pct, entry_low, entry_high,
                    stop_loss, take_profit, reasoning, skip_reason, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f["session_id"], f["analysis_id"], f["event_date"],
                 f.get("prev_signal"), f["new_signal"], f.get("advice_action"),
                 f["action"], f.get("shares_delta", 0), f.get("price"),
                 f.get("trade_id"), f.get("confidence"),
                 f.get("target_position_pct"), f.get("entry_low"),
                 f.get("entry_high"), f.get("stop_loss"), f.get("take_profit"),
                 f.get("reasoning"), f.get("skip_reason"), _now_iso()),
            )
            return int(cur.lastrowid)

    def list_strategy_events(self, session_id: int, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_strategy_events
                   WHERE session_id = ? ORDER BY event_date DESC, id DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_strategy_event(self, session_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM paper_trade_strategy_events
                   WHERE session_id = ? ORDER BY event_date DESC, id DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    # ── Daily stats ────────────────────────────────────────────────────

    def upsert_daily_stat(self, **f) -> None:
        required = ("session_id", "date", "cash", "total_value")
        for k in required:
            if f.get(k) is None:
                raise ValueError(f"upsert_daily_stat missing {k}")
        cols = ("session_id", "date", "open_price", "high_price", "low_price",
                "close_price", "position_shares", "avg_cost", "position_value",
                "cash", "total_value", "daily_pnl", "daily_pnl_pct",
                "cum_pnl", "cum_pnl_pct", "drawdown_pct", "active_signal",
                "active_analysis_id", "days_held", "strategy_changed")
        vals = [f.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("session_id", "date"))
        with self._lock, self._conn() as conn:
            conn.execute(
                f"INSERT INTO paper_trade_daily_stats ({','.join(cols)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(session_id, date) DO UPDATE SET {updates}",
                vals,
            )

    def list_daily_stats(self, session_id: int, limit: int = 1000) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_daily_stats
                   WHERE session_id = ? ORDER BY date ASC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_daily_stat(self, session_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM paper_trade_daily_stats
                   WHERE session_id = ? ORDER BY date DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    # ── Positions ──────────────────────────────────────────────────────

    def get_open_trade(self, session_id: int, ticker: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM paper_trade_trades
                   WHERE session_id = ? AND ticker = ? AND exit_date IS NULL
                   ORDER BY entry_date DESC LIMIT 1""",
                (session_id, ticker.upper()),
            ).fetchone()
            return dict(row) if row else None

    def insert_open_trade(self, session_id: int, ticker: str,
                          entry_analysis_id: int, entry_date: str,
                          entry_price: float, shares: float,
                          stop_loss: float | None, take_profit: float | None) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trade_trades
                   (session_id, ticker, entry_analysis_id, entry_date,
                    entry_price, shares, stop_loss, take_profit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, ticker.upper(), entry_analysis_id, entry_date,
                 entry_price, shares, stop_loss, take_profit),
            )
            return int(cur.lastrowid)

    def update_open_trade(self, trade_id: int, **f) -> None:
        if not f: return
        allowed = {"shares", "entry_price", "stop_loss", "take_profit"}
        sets, vals = [], []
        for k, v in f.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets: return
        vals.append(trade_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE paper_trade_trades SET {','.join(sets)} WHERE id = ?",
                vals,
            )

    def close_open_trade(self, trade_id: int, exit_date: str, exit_price: float,
                         exit_reason: str, exit_analysis_id: int | None = None) -> dict:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trade_trades WHERE id = ?", (trade_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Trade {trade_id} not found")
            t = dict(row)
            pnl = (exit_price - t["entry_price"]) * t["shares"]
            pnl_pct = (exit_price / t["entry_price"] - 1) * 100 if t["entry_price"] else 0
            from datetime import date as _d
            try:
                d1 = datetime.strptime(t["entry_date"], "%Y-%m-%d").date()
                d2 = datetime.strptime(exit_date, "%Y-%m-%d").date()
                hold = (d2 - d1).days
            except Exception:
                hold = 0
            conn.execute(
                """UPDATE paper_trade_trades
                   SET exit_date = ?, exit_price = ?, exit_reason = ?,
                       exit_analysis_id = ?, pnl = ?, pnl_pct = ?, hold_days = ?
                   WHERE id = ?""",
                (exit_date, exit_price, exit_reason, exit_analysis_id,
                 round(pnl, 4), round(pnl_pct, 4), hold, trade_id),
            )
            t.update(exit_date=exit_date, exit_price=exit_price,
                     exit_reason=exit_reason, pnl=round(pnl, 4),
                     pnl_pct=round(pnl_pct, 4), hold_days=hold)
            return t

    # ── Trading plans & planned orders (V3) ────────────────────────────

    def save_plan(self, *, session_id: int, analysis_id: int,
                   rating: str | None, thesis: str | None,
                   holding_months: tuple[int | None, int | None] | None,
                   raw_summary: str | None,
                   plan: dict, parse_method: str) -> int:
        """Insert a trading_plan + its planned_orders atomically.

        F1 dedup: if the active plan has the same content fingerprint,
        only increment reconfirmed_count (no new plan row).
        """
        hm = holding_months or (None, None)
        fp = _plan_fingerprint(plan)

        with self._lock, self._conn() as conn:
            # F1: dedup — check if active plan has same fingerprint
            existing = conn.execute(
                """SELECT id FROM paper_trade_plans
                   WHERE session_id=? AND status='active' AND fingerprint=?""",
                (session_id, fp),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE paper_trade_plans
                       SET reconfirmed_count = COALESCE(reconfirmed_count, 1) + 1,
                           reconfirmed_at = ?,
                           analysis_ids = json_insert(COALESCE(analysis_ids,'[]'), '$[#]', ?)
                       WHERE id = ?""",
                    (_now_iso(), analysis_id, existing[0]),
                )
                return int(existing[0])

            # Mark previous active plan(s) as superseded
            now = _now_iso()
            conn.execute(
                """UPDATE paper_trade_plans SET status='superseded',
                                                superseded_at=?
                   WHERE session_id=? AND status='active'""",
                (now, session_id),
            )
            # Insert new plan with fingerprint
            cur = conn.execute(
                """INSERT INTO paper_trade_plans
                   (session_id, analysis_id, rating, thesis,
                    holding_months_min, holding_months_max,
                    raw_summary, plan_json, parse_method,
                    status, fingerprint, analysis_ids, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'active',?,json_array(?),?)""",
                (session_id, analysis_id, rating, thesis,
                 hm[0], hm[1], raw_summary,
                 json.dumps(plan, ensure_ascii=False),
                 parse_method, fp, analysis_id, now),
            )
            plan_id = int(cur.lastrowid)

            # Supersede old pending orders (but preserve them as history)
            conn.execute(
                """UPDATE paper_trade_planned_orders
                   SET status='superseded', superseded_by_plan_id=?, superseded_at=?
                   WHERE session_id=? AND status='pending'""",
                (plan_id, now, session_id),
            )

            # Back-link the newly superseded plan to its successor
            conn.execute(
                """UPDATE paper_trade_plans SET superseded_by_plan_id=?
                   WHERE session_id=? AND status='superseded'
                     AND superseded_by_plan_id IS NULL AND id != ?""",
                (plan_id, session_id, plan_id),
            )

            # Insert planned_orders
            for i, o in enumerate(plan.get("orders", []), start=1):
                trig = o.get("trigger") or {}
                conn.execute(
                    """INSERT INTO paper_trade_planned_orders
                       (plan_id, session_id, order_type, sequence,
                        pct_target_total, trigger_kind, trigger_json,
                        status, description, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (plan_id, session_id, o.get("type"), i,
                     o.get("pct_target_total"),
                     trig.get("kind") or "immediate",
                     json.dumps(trig, ensure_ascii=False),
                     # Immediate orders stay pending until evaluator picks them up
                     "pending",
                     o.get("desc") or o.get("description"),
                     now),
                )
            return plan_id

    def get_active_plan(self, session_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM paper_trade_plans
                   WHERE session_id=? AND status='active'
                   ORDER BY id DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return _row_to_plan(row) if row else None

    def list_plans(self, session_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_trade_plans
                   WHERE session_id=? ORDER BY created_at DESC""",
                (session_id,),
            ).fetchall()
        return [_row_to_plan(r) for r in rows]

    def get_plan(self, plan_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trade_plans WHERE id=?", (plan_id,),
            ).fetchone()
            return _row_to_plan(row) if row else None

    def list_orders(self, *, plan_id: int | None = None,
                    session_id: int | None = None,
                    status: str | None = None) -> list[dict]:
        q = "SELECT * FROM paper_trade_planned_orders WHERE 1=1"
        args = []
        if plan_id is not None:
            q += " AND plan_id = ?"; args.append(plan_id)
        if session_id is not None:
            q += " AND session_id = ?"; args.append(session_id)
        if status is not None:
            q += " AND status = ?"; args.append(status)
        q += " ORDER BY sequence ASC, id ASC"
        with self._conn() as conn:
            rows = conn.execute(q, args).fetchall()
        return [_row_to_order(r) for r in rows]

    def mark_order_triggered(self, order_id: int, *,
                              triggered_date: str, triggered_price: float,
                              trade_id: int | None) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """UPDATE paper_trade_planned_orders
                   SET status='triggered', triggered_date=?,
                       triggered_price=?, trade_id=?
                   WHERE id=?""",
                (triggered_date, triggered_price, trade_id, order_id),
            )

    def cancel_order(self, order_id: int) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE paper_trade_planned_orders SET status='cancelled' WHERE id=?",
                (order_id,),
            )

    # Attach
    PaperTradeStore.save_plan = save_plan
    PaperTradeStore.get_active_plan = get_active_plan
    PaperTradeStore.list_plans = list_plans
    PaperTradeStore.get_plan = get_plan
    PaperTradeStore.list_orders = list_orders
    PaperTradeStore.mark_order_triggered = mark_order_triggered
    PaperTradeStore.cancel_order = cancel_order

    PaperTradeStore.find_session_by_ticker = find_session_by_ticker
    PaperTradeStore.create_ticker_session = create_ticker_session
    PaperTradeStore.list_ticker_sessions = list_ticker_sessions
    PaperTradeStore.update_session_last_eod = update_session_last_eod
    PaperTradeStore.insert_strategy_event = insert_strategy_event
    PaperTradeStore.list_strategy_events = list_strategy_events
    PaperTradeStore.latest_strategy_event = latest_strategy_event
    PaperTradeStore.upsert_daily_stat = upsert_daily_stat
    PaperTradeStore.list_daily_stats = list_daily_stats
    PaperTradeStore.last_daily_stat = last_daily_stat
    PaperTradeStore.get_open_trade = get_open_trade
    PaperTradeStore.insert_open_trade = insert_open_trade
    PaperTradeStore.update_open_trade = update_open_trade
    PaperTradeStore.close_open_trade = close_open_trade


_v2_methods()
