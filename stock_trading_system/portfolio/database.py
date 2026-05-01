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


VALID_DEPTHS = ("quick", "standard", "deep")


def _normalize_depth(v) -> str:
    """Coerce ``depth`` to one of {quick, standard, deep}; default standard.

    Centralised so workers, save_analysis, and the API DTO all agree on
    the canonical set. Anything we don't recognise falls back to
    ``standard`` rather than failing loudly — depth is a UX hint, not a
    safety-critical invariant.
    """
    if v is None:
        return "standard"
    s = str(v).strip().lower()
    return s if s in VALID_DEPTHS else "standard"


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
            # Private tables embed user_id from creation. Composite UNIQUE
            # over (user_id, ticker|date) is what `upsert_position` /
            # `save_snapshot` ON CONFLICT clauses target — without it,
            # two users with the same ticker (or same-day snapshot) collide
            # on the legacy single-tenant primary key.
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    ticker TEXT NOT NULL,
                    market TEXT NOT NULL,
                    shares REAL NOT NULL,
                    avg_cost REAL NOT NULL,
                    added_date TEXT NOT NULL,
                    UNIQUE(user_id, ticker)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    date TEXT NOT NULL,
                    total_value REAL NOT NULL,
                    total_cost REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    positions_json TEXT NOT NULL,
                    UNIQUE(user_id, date)
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    ticker TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    created TEXT NOT NULL,
                    triggered INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS ix_positions_user
                    ON positions(user_id, ticker);
                CREATE INDEX IF NOT EXISTS ix_transactions_user
                    ON transactions(user_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS ix_daily_snapshots_user
                    ON daily_snapshots(user_id, date DESC);
                CREATE INDEX IF NOT EXISTS ix_alerts_user
                    ON alerts(user_id, ticker);

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
                    steps_json TEXT,
                    rendering_json TEXT,
                    -- v1.14 provenance: who ran this, with which LLM, hashed
                    -- LLM config so the same prompt+model collapses to one
                    -- cache hit, plus task_id back-reference and timing.
                    -- bookmarked is a per-row legacy bit; the canonical
                    -- per-user bookmark lives in `analysis_bookmarks` so
                    -- two users can independently star the same shared row.
                    created_by INTEGER,
                    provider TEXT,
                    config_hash TEXT,
                    task_id TEXT,
                    duration_sec REAL,
                    bookmarked INTEGER DEFAULT 0,
                    -- v1.16: analysis depth UX hint (quick/standard/deep).
                    -- Drives whether the worker enables iterative reasoning
                    -- and is surfaced on the detail page so users see what
                    -- they paid for.
                    depth TEXT DEFAULT 'standard'
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

                -- v1.14: split per-user advice from shared research.
                -- analysis_history holds the shared report; this table
                -- holds the holdings-aware position-sizing advice that
                -- depends on the requester's portfolio. Per-user UNIQUE
                -- so a user can re-run advice on the same shared row
                -- (e.g. after adding a position) and replace cleanly.
                CREATE TABLE IF NOT EXISTS user_analysis_advice (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    analysis_id INTEGER NOT NULL,
                    holdings_context_snapshot TEXT,
                    action TEXT,
                    confidence TEXT,
                    position_pct REAL,
                    entry_low REAL,
                    entry_high REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    reasoning TEXT,
                    risk_warning TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, analysis_id),
                    FOREIGN KEY(analysis_id)
                        REFERENCES analysis_history(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_uaa_user
                    ON user_analysis_advice(user_id, created_at DESC);

                -- v1.14: per-user bookmarks. Two users can independently
                -- star the same shared analysis row.
                CREATE TABLE IF NOT EXISTS analysis_bookmarks (
                    user_id INTEGER NOT NULL,
                    analysis_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, analysis_id),
                    FOREIGN KEY(analysis_id)
                        REFERENCES analysis_history(id) ON DELETE CASCADE
                );

                -- v1.14: lightweight per-user watchlist. Receives the
                -- analyses the "加入持仓追踪" button targets when the
                -- user hasn't (yet) wired paper_trade.
                CREATE TABLE IF NOT EXISTS user_watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    analysis_id INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, ticker)
                );
            """)
            self._migrate_private_tables_user_id(conn)
            self._migrate_analysis_history(conn)

    def _migrate_private_tables_user_id(self, conn: sqlite3.Connection):
        """Add user_id to legacy single-tenant private tables.

        Legacy DBs (pre-multi-tenant) created ``positions``/``transactions``/
        ``daily_snapshots``/``alerts`` without ``user_id``. ALTER TABLE ADD
        COLUMN is idempotent enough — once the column exists this is a no-op.
        Composite UNIQUE indices restore per-user identity (same ticker
        owned by two users no longer collides on the legacy ticker PK).

        NULL ``user_id`` rows are backfilled to the first active user
        (typically admin) so existing data isn't orphaned and remains
        visible to *some* tenant rather than vanishing under the new
        per-user filters.
        """
        for table in ("positions", "transactions", "daily_snapshots", "alerts"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "user_id" not in cols:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")
                except sqlite3.OperationalError as e:
                    logger.warning("ALTER %s.user_id failed: %s", table, e)

        for sql in (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_user_ticker "
            "ON positions(user_id, ticker)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_snapshots_user_date "
            "ON daily_snapshots(user_id, date)",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                logger.warning("create unique idx failed: %s", e)

        try:
            row = conn.execute(
                "SELECT id FROM users WHERE status='active' "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            default_uid = row["id"] if row else None
        except sqlite3.OperationalError:
            default_uid = None
        if default_uid is not None:
            for table in ("positions", "transactions", "daily_snapshots", "alerts"):
                try:
                    conn.execute(
                        f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
                        (default_uid,),
                    )
                except sqlite3.OperationalError as e:
                    logger.warning("backfill %s.user_id failed: %s", table, e)

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
            # v1.14 provenance columns. ALTER TABLE ADD COLUMN is idempotent
            # — pre-existing rows get NULL, fine for a shared library that
            # didn't capture this metadata before.
            ("created_by", "INTEGER"),
            ("provider", "TEXT"),
            ("config_hash", "TEXT"),
            ("task_id", "TEXT"),
            ("duration_sec", "REAL"),
            ("bookmarked", "INTEGER DEFAULT 0"),
            # v1.16: depth (quick/standard/deep) — UX hint surfaced on
            # the detail page. Old rows with NULL get treated as
            # 'standard' by the API DTO via _normalize_depth.
            ("depth", "TEXT DEFAULT 'standard'"),
            # v1.19: per-tab structured cards extracted from the analyzer
            # reports. JSON blob shaped like
            # ``{"summary": {...} | None, "Market": {...} | None, ...}``.
            # Empty string when extraction was skipped (e.g. quick depth or
            # extractor failure); the DTO parses it into a dict and the
            # frontend falls back to markdown when a key is missing or null.
            ("rendering_json", "TEXT"),
        ]
        for name, typ in additions:
            if name not in cols:
                try:
                    conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {name} {typ}")
                except sqlite3.OperationalError as e:
                    logger.warning("Migration for column %s failed: %s", name, e)

        # v1.16 SECURITY MIGRATION: pre-v1.14 rows had per-user advice
        # baked into the shared row's advice_json + structured columns.
        # We can't safely keep them around — any other reader would
        # inherit the original creator's holdings-aware plan. Hoist to
        # user_analysis_advice (keyed on the row's created_by) when we
        # can, then null out the shared columns. If created_by is NULL
        # we just clear the shared columns: the data is anonymous and
        # cannot be attributed to a specific tenant.
        try:
            rows = conn.execute(
                "SELECT id, created_by, advice_json FROM analysis_history "
                "WHERE advice_json IS NOT NULL AND advice_json != ''"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows:
            try:
                adv = json.loads(r["advice_json"])
            except Exception:
                adv = None
            if isinstance(adv, dict) and r["created_by"] is not None:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO user_analysis_advice
                           (user_id, analysis_id, holdings_context_snapshot,
                            action, confidence, position_pct,
                            entry_low, entry_high, stop_loss, take_profit,
                            reasoning, risk_warning, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            int(r["created_by"]), int(r["id"]), "",
                            adv.get("action"),
                            adv.get("confidence"),
                            _coerce_float(adv.get("suggested_position_pct")),
                            _coerce_float(adv.get("entry_price_low")),
                            _coerce_float(adv.get("entry_price_high")),
                            _coerce_float(adv.get("stop_loss")),
                            _coerce_float(adv.get("take_profit")),
                            adv.get("reasoning") or "",
                            adv.get("risk_warning") or "",
                            ts,
                        ),
                    )
                except sqlite3.OperationalError as e:
                    logger.warning("hoist legacy advice → user_advice failed: %s", e)
            try:
                conn.execute(
                    """UPDATE analysis_history SET
                         advice_json = '',
                         action = NULL, confidence = NULL, position_pct = NULL,
                         entry_low = NULL, entry_high = NULL,
                         stop_loss = NULL, take_profit = NULL
                       WHERE id = ?""",
                    (int(r["id"]),),
                )
            except sqlite3.OperationalError as e:
                logger.warning("strip shared advice cols failed: %s", e)

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
                """INSERT INTO daily_snapshots
                   (user_id, date, total_value, total_cost, pnl, pnl_pct, positions_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, date) DO UPDATE SET
                     total_value = excluded.total_value,
                     total_cost = excluded.total_cost,
                     pnl = excluded.pnl,
                     pnl_pct = excluded.pnl_pct,
                     positions_json = excluded.positions_json""",
                (snapshot.user_id, snapshot.date, snapshot.total_value,
                 snapshot.total_cost, snapshot.pnl, snapshot.pnl_pct,
                 snapshot.positions_json),
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
        """Insert a *shared research* analysis row. Returns the new row id.

        SECURITY contract (matches ``TaskStore._save_analysis_result``):
        the per-user advice payload — action / entry / stop_loss /
        take_profit / position_pct / confidence — is **never** persisted
        on this shared row. Pre-v1.14 code used to extract those fields
        from ``data["advice_json"]`` and write them to the shared
        ``analysis_history`` columns, which silently leaked the original
        creator's holdings-aware plan to every other user reading the
        record. We now ignore any caller-supplied ``advice_json`` here:
        ``advice_json`` is forced to ``""`` and the structured advice
        columns are forced to NULL.

        Callers that legitimately need to persist a user's advice should:
            row_id = db.save_analysis(shared_payload)
            db.save_user_advice(user_id, row_id, advice_dict)

        That keeps the per-user payload in ``user_analysis_advice`` so
        cross-user reads cannot inherit it.
        """
        steps_raw = data.get("steps_json") or ""
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO analysis_history
                   (ticker, date, signal, market_report, sentiment_report,
                    news_report, fundamentals_report, investment_debate,
                    risk_assessment, trade_decision, advice_json, created_at,
                    action, confidence, position_pct,
                    entry_low, entry_high, stop_loss, take_profit, model, steps_json,
                    created_by, provider, config_hash, task_id, duration_sec, bookmarked,
                    depth, rendering_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["ticker"], data["date"], data["signal"],
                    data.get("market_report", ""),
                    data.get("sentiment_report", ""),
                    data.get("news_report", ""),
                    data.get("fundamentals_report", ""),
                    data.get("investment_debate", ""),
                    data.get("risk_assessment", ""),
                    data.get("trade_decision", ""),
                    "",                          # advice_json — see docstring
                    data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    None,                        # action
                    None,                        # confidence
                    None,                        # position_pct
                    None,                        # entry_low
                    None,                        # entry_high
                    None,                        # stop_loss
                    None,                        # take_profit
                    data.get("model"),
                    steps_raw,
                    data.get("created_by"),
                    data.get("provider"),
                    data.get("config_hash"),
                    data.get("task_id"),
                    _coerce_float(data.get("duration_sec")),
                    int(bool(data.get("bookmarked", 0))),
                    _normalize_depth(data.get("depth")),
                    data.get("rendering_json", ""),
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

    # Columns returned by compare/timeline queries — keep heavy report
    # text out so the payload stays small and mobile-friendly. The
    # per-user advice columns (action/confidence/position_pct/entry_low/
    # entry_high/stop_loss/take_profit) are intentionally omitted: those
    # belong to one tenant only and live in user_analysis_advice. If a
    # caller wants to layer the requesting user's advice onto the
    # comparison view, they pull from get_user_advice() and merge in the
    # API layer.
    _STRUCTURED_COLS = (
        "id, ticker, date, signal, created_at, model, "
        "provider, config_hash, task_id, duration_sec, depth, "
        "created_by, bookmarked"
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

    # ── User-scoped advice + bookmarks (v1.14) ───────────────────────────

    def save_user_advice(
        self,
        user_id: int,
        analysis_id: int,
        advice: dict,
        holdings_snapshot: str | None = None,
    ) -> int:
        """UPSERT this user's advice for this shared analysis row.

        Replaces any prior advice for (user_id, analysis_id) so re-running
        with a fresh holdings snapshot stays single-row.
        """
        adv = advice or {}
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO user_analysis_advice
                   (user_id, analysis_id, holdings_context_snapshot,
                    action, confidence, position_pct,
                    entry_low, entry_high, stop_loss, take_profit,
                    reasoning, risk_warning, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, analysis_id) DO UPDATE SET
                     holdings_context_snapshot = excluded.holdings_context_snapshot,
                     action = excluded.action,
                     confidence = excluded.confidence,
                     position_pct = excluded.position_pct,
                     entry_low = excluded.entry_low,
                     entry_high = excluded.entry_high,
                     stop_loss = excluded.stop_loss,
                     take_profit = excluded.take_profit,
                     reasoning = excluded.reasoning,
                     risk_warning = excluded.risk_warning,
                     created_at = excluded.created_at""",
                (
                    int(user_id), int(analysis_id), holdings_snapshot or "",
                    adv.get("action"),
                    adv.get("confidence"),
                    _coerce_float(adv.get("suggested_position_pct")),
                    _coerce_float(adv.get("entry_price_low")),
                    _coerce_float(adv.get("entry_price_high")),
                    _coerce_float(adv.get("stop_loss")),
                    _coerce_float(adv.get("take_profit")),
                    adv.get("reasoning") or "",
                    adv.get("risk_warning") or "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            return int(cur.lastrowid)

    def get_user_advice(self, user_id: int, analysis_id: int) -> dict | None:
        """Return the requesting user's per-analysis advice (or None)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_analysis_advice "
                "WHERE user_id = ? AND analysis_id = ?",
                (int(user_id), int(analysis_id)),
            ).fetchone()
            return dict(row) if row else None

    def get_user_advice_bulk(self, user_id: int,
                              analysis_ids: list[int]) -> dict[int, dict]:
        """Return ``{analysis_id: advice_row}`` for every id this user
        owns advice on. Lets compare/timeline DTOs layer the requesting
        user's advice onto the shared rows in one query.
        """
        if not analysis_ids:
            return {}
        safe_ids = [int(i) for i in analysis_ids]
        placeholders = ",".join("?" * len(safe_ids))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM user_analysis_advice "
                f"WHERE user_id = ? AND analysis_id IN ({placeholders})",
                [int(user_id), *safe_ids],
            ).fetchall()
        return {int(r["analysis_id"]): dict(r) for r in rows}

    def get_analysis_creator(self, analysis_id: int) -> int | None:
        """Return ``created_by`` for this row (None when missing/legacy)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT created_by FROM analysis_history WHERE id = ?",
                (int(analysis_id),),
            ).fetchone()
            return int(row["created_by"]) if row and row["created_by"] is not None else None

    def set_bookmark(self, user_id: int, analysis_id: int, bookmarked: bool) -> bool:
        """Toggle a per-user bookmark; returns the new state."""
        with self._get_conn() as conn:
            if bookmarked:
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_bookmarks "
                    "(user_id, analysis_id, created_at) VALUES (?, ?, ?)",
                    (int(user_id), int(analysis_id),
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                return True
            conn.execute(
                "DELETE FROM analysis_bookmarks "
                "WHERE user_id = ? AND analysis_id = ?",
                (int(user_id), int(analysis_id)),
            )
            return False

    def is_bookmarked(self, user_id: int, analysis_id: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM analysis_bookmarks "
                "WHERE user_id = ? AND analysis_id = ?",
                (int(user_id), int(analysis_id)),
            ).fetchone()
            return row is not None

    def add_to_watchlist(
        self,
        user_id: int,
        ticker: str,
        analysis_id: int | None = None,
    ) -> int:
        """Idempotent — same (user, ticker) just refreshes the timestamp."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO user_watchlist
                   (user_id, ticker, analysis_id, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, ticker) DO UPDATE SET
                     analysis_id = excluded.analysis_id,
                     created_at = excluded.created_at""",
                (int(user_id), ticker.upper(), analysis_id, ts),
            )
            return int(cur.lastrowid or 0)
