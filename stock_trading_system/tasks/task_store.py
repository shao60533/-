"""SQLite persistence for async tasks — full lifecycle record + result ref.

Schema: see TECHNICAL_DESIGN / ARCHITECTURE_UPGRADE_PROPOSAL §4.2.2.

Design notes:
- One row per task, covering pending → running → success/failed/cancelled.
- `params_hash` enables idempotency lookup (same params within a time window
  returns existing task instead of creating a duplicate).
- `result_ref` points to a business table (e.g. "analysis_history:42"). The
  business table owns the real result; tasks table stays small.
- Thread-safe via short-lived connections + WAL mode.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from stock_trading_system.utils import get_logger

logger = get_logger("tasks.store")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER DEFAULT 0,
    progress_step TEXT,
    result_ref TEXT,
    error_message TEXT,
    error_trace TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    retry_of TEXT,
    params_hash TEXT,
    created_by TEXT DEFAULT 'user'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type_created ON tasks(type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_params_hash ON tasks(params_hash, status);
"""


# ── Helpers ──────────────────────────────────────────────────────────────────


def now_iso() -> str:
    """ISO 8601 timestamp in local time (second precision)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_params(task_type: str, params: dict) -> str:
    """Stable hash of (task_type, params) — key order independent.

    Underscore-prefixed keys (``__user_id__``, ``__task_id__``,
    ``__cancel_event__``) are TaskManager internals injected by the
    submit / run layer; including them would make alice's "AAPL today"
    a different cache entry from bob's, defeating shared-research dedup.
    """
    public = {k: v for k, v in (params or {}).items() if not str(k).startswith("__")}
    payload = json.dumps(
        {"t": task_type, "p": public},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _safe_float(v) -> float | None:
    """Coerce best-effort to float; None / unparseable → None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ── TaskStore ────────────────────────────────────────────────────────────────


class TaskStore:
    """Thread-safe SQLite-backed task record store."""

    # Fields that update() accepts. Others are ignored silently.
    _UPDATABLE = frozenset({
        "status", "progress", "progress_step", "result_ref",
        "error_message", "error_trace",
        "started_at", "completed_at", "duration_ms", "retry_of",
    })

    def __init__(self, db_path: str):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # serialize writes on SQLite
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init(self):
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── CRUD ─────────────────────────────────────────────────────────────

    def insert(self, task: dict) -> dict:
        """Insert a new task row. Fills `created_at` if missing.

        Required keys: id, type, title, params_json, status.
        Optional: params_hash, created_by, retry_of.
        """
        row = {
            "id": task["id"],
            "type": task["type"],
            "title": task["title"],
            "params_json": task["params_json"],
            "status": task["status"],
            "progress": task.get("progress", 0),
            "progress_step": task.get("progress_step"),
            "result_ref": task.get("result_ref"),
            "error_message": task.get("error_message"),
            "error_trace": task.get("error_trace"),
            "created_at": task.get("created_at") or now_iso(),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "duration_ms": task.get("duration_ms"),
            "retry_of": task.get("retry_of"),
            "params_hash": task.get("params_hash"),
            "created_by": task.get("created_by", "user"),
        }
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, type, title, params_json, status, progress, progress_step,
                    result_ref, error_message, error_trace,
                    created_at, started_at, completed_at, duration_ms,
                    retry_of, params_hash, created_by)
                   VALUES (:id, :type, :title, :params_json, :status, :progress,
                           :progress_step, :result_ref, :error_message, :error_trace,
                           :created_at, :started_at, :completed_at, :duration_ms,
                           :retry_of, :params_hash, :created_by)""",
                row,
            )
        return self.get(row["id"])

    def update(self, task_id: str, **fields) -> dict | None:
        """Update specified fields. Unknown fields silently skipped."""
        safe = {k: v for k, v in fields.items() if k in self._UPDATABLE}
        if not safe:
            return self.get(task_id)
        sets = ", ".join(f"{k} = :{k}" for k in safe)
        safe["_id"] = task_id
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id = :_id", safe)
        return self.get(task_id)

    def get(self, task_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete(self, task_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    # Allow-list of task types whose results are shared research artefacts.
    # Any logged-in user may *read* a task of one of these types created by
    # another user. Mutations (cancel/delete/retry) still require owner/admin.
    # Covers: AI analysis, all screener variants, backtests, public reports.
    SHARED_TYPES = frozenset([
        "analysis", "screen", "screen_v2", "screen_v3",
        "backtest", "report",
    ])
    # Documented private types — kept for the ``shared_research`` listing
    # filter and as a reminder of which categories are user-specific. NOTE
    # that this is **not** the access-check source of truth: the web layer
    # now default-denies anything that is not in SHARED_TYPES. So new task
    # types that nobody has classified yet stay owner-only by default.
    PRIVATE_TYPES = frozenset([
        "portfolio_batch", "batch_analysis", "personal_advice",
        "alerts", "paper_trade", "paper_backfill",
        "backfill_snapshots",
    ])

    VALID_SCOPES = frozenset({"mine", "shared_research", "all"})

    @classmethod
    def is_shared_type(cls, task_type: str) -> bool:
        """Single source of truth for "is this task type cross-user readable?"

        The web ownership check defers to this so adding a new type to
        ``SHARED_TYPES`` is enough — no parallel allow-list to keep in sync.
        """
        return task_type in cls.SHARED_TYPES

    def _scope_clause(
        self,
        scope: str | None,
        created_by: int | None,
    ) -> tuple[str | None, list[Any]]:
        """Return (sql_fragment, params) for the given scope.

        Contract:
            * ``scope=None`` = programmatic / admin listing — no scope filter
              applied. The HTTP layer is expected to never forward a None.
            * ``scope="all"`` = explicit no-filter (admin only at HTTP layer).
            * ``scope="shared_research"`` = restrict to SHARED_TYPES.
            * ``scope="mine"`` = restrict to ``created_by``. With no caller id
              we return an impossible predicate rather than leaking everything.
            * Any other (unknown) scope falls through to "mine" semantics so a
              typo at a future API caller can never bypass filtering and leak
              other users' private tasks.
        """
        if scope is None:
            return None, []
        if scope == "all":
            return None, []
        if scope == "shared_research":
            types = sorted(self.SHARED_TYPES)
            placeholders = ",".join("?" * len(types))
            return f"type IN ({placeholders})", list(types)
        # "mine" or unknown → defensive owner filter
        if created_by is None:
            return "1 = 0", []
        return "created_by = ?", [str(created_by)]

    def list(
        self,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        created_by: int | None = None,
        scope: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_type:
            clauses.append("type = ?")
            params.append(task_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        scope_sql, scope_params = self._scope_clause(scope, created_by)
        if scope_sql:
            clauses.append(scope_sql)
            params.extend(scope_params)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([int(limit), int(offset)])
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where} "
                f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def count(
        self,
        task_type: str | None = None,
        status: str | None = None,
        created_by: int | None = None,
        scope: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if task_type:
            clauses.append("type = ?")
            params.append(task_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        scope_sql, scope_params = self._scope_clause(scope, created_by)
        if scope_sql:
            clauses.append(scope_sql)
            params.extend(scope_params)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()
            return row[0] if row else 0

    # ── Idempotency ──────────────────────────────────────────────────────

    def find_recent_by_hash(
        self,
        params_hash: str,
        window_seconds: int,
        statuses: Iterable[str] = ("pending", "running", "success"),
    ) -> dict | None:
        """Find recent task with same params_hash within window.

        Returns the most recent match whose status is in *statuses*.
        """
        cutoff = (datetime.now() - timedelta(seconds=max(0, window_seconds))) \
            .strftime("%Y-%m-%d %H:%M:%S")
        statuses = tuple(statuses)
        if not statuses:
            return None
        placeholders = ",".join("?" * len(statuses))
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM tasks "
                f"WHERE params_hash = ? AND status IN ({placeholders}) "
                f"  AND created_at >= ? "
                f"ORDER BY created_at DESC LIMIT 1",
                (params_hash, *statuses, cutoff),
            ).fetchone()
            return dict(row) if row else None

    # ── Result handoff ───────────────────────────────────────────────────

    def save_result(self, task_type: str, task_id: str, result: dict) -> str:
        """Write result to its business table and return a result_ref.

        Format: "<table_name>:<row_id>". The caller later uses load_result()
        to retrieve it. Falls back to storing JSON blob in a generic table
        when no specific business table is known.
        """
        # Route by task_type. Extend here as new workers land.
        if task_type == "analysis":
            return self._save_analysis_result(task_id, result)
        if task_type == "screen":
            return self._save_screen_result(task_id, result)
        if task_type == "backtest":
            return self._save_backtest_result(task_id, result)
        # Generic fallback — stash JSON in the task row itself.
        return self._save_generic_result(task_id, result)

    def load_result(self, result_ref: str) -> dict | None:
        """Load a result by its reference string."""
        if not result_ref or ":" not in result_ref:
            return None
        table, rid = result_ref.split(":", 1)
        with self._conn() as conn:
            if table == "task_results_generic":
                row = conn.execute(
                    "SELECT payload FROM task_results_generic WHERE id = ?",
                    (rid,),
                ).fetchone()
                if not row:
                    return None
                try:
                    return json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    return None
            try:
                row = conn.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (int(rid),)
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            return dict(row) if row else None

    def _save_analysis_result(self, task_id: str, result: dict) -> str:
        """Persist a worker's analysis result as a *shared research* row.

        SECURITY: any ``advice``/``_advice_payload`` data in ``result`` is
        intentionally **dropped here**. The per-user advice payload — action,
        entry/exit prices, stop loss, position sizing, reasoning — depends on
        the requester's holdings and must NEVER live on a row that other
        users can read. The TaskManager post-save hook persists it to the
        ``user_analysis_advice`` table instead. This row holds only what
        every logged-in user is allowed to see (reports + provenance).
        """
        self._ensure_analysis_history_table()

        steps_json = result.get("steps_json")
        if steps_json is None:
            steps = result.get("steps")
            if steps is not None:
                try:
                    steps_json = json.dumps(steps, ensure_ascii=False)
                except (TypeError, ValueError):
                    steps_json = None
        # Late-bind to avoid a circular import at module load time —
        # task_store is imported before portfolio.database in some boot
        # sequences (CLI / migration tooling).
        from stock_trading_system.portfolio.database import _normalize_depth
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO analysis_history
                   (ticker, date, signal, market_report, sentiment_report,
                    news_report, fundamentals_report, investment_debate,
                    risk_assessment, trade_decision, advice_json, created_at,
                    action, confidence, position_pct,
                    entry_low, entry_high, stop_loss, take_profit,
                    model, steps_json,
                    created_by, provider, config_hash, task_id, duration_sec, bookmarked,
                    depth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.get("ticker", ""), result.get("date", ""),
                    result.get("signal", ""),
                    result.get("market_report", ""),
                    result.get("sentiment_report", ""),
                    result.get("news_report", ""),
                    result.get("fundamentals_report", ""),
                    result.get("investment_debate", ""),
                    result.get("risk_assessment", ""),
                    result.get("trade_decision", ""),
                    # Per-user advice columns are intentionally NULL on the
                    # shared row. See class docstring above.
                    "",                          # advice_json
                    now_iso(),                   # created_at
                    None,                        # action
                    None,                        # confidence
                    None,                        # position_pct
                    None,                        # entry_low
                    None,                        # entry_high
                    None,                        # stop_loss
                    None,                        # take_profit
                    result.get("model"),
                    steps_json,
                    result.get("created_by"),
                    result.get("provider"),
                    result.get("config_hash"),
                    result.get("task_id") or task_id,
                    _safe_float(result.get("duration_sec")),
                    0,
                    _normalize_depth(result.get("depth")),
                ),
            )
            return f"analysis_history:{cur.lastrowid}"

    def _save_screen_result(self, task_id: str, result: dict) -> str:
        self._ensure_screen_table()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO screen_results
                   (task_id, market, strategy, results_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    task_id, result.get("market", ""), result.get("strategy", ""),
                    json.dumps(result.get("results", []), ensure_ascii=False),
                    now_iso(),
                ),
            )
            return f"screen_results:{cur.lastrowid}"

    def _save_backtest_result(self, task_id: str, result: dict) -> str:
        self._ensure_backtest_table()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO backtest_results
                   (task_id, ticker, strategy_id, period, initial_capital,
                    metrics_json, equity_curve_json, trades_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, result.get("ticker", ""),
                    result.get("strategy_id", ""),
                    result.get("period", ""),
                    float(result.get("initial_capital", 0) or 0),
                    json.dumps(result.get("metrics", {}), ensure_ascii=False),
                    json.dumps(result.get("equity_curve", []), ensure_ascii=False),
                    json.dumps(result.get("trades", []), ensure_ascii=False),
                    now_iso(),
                ),
            )
            return f"backtest_results:{cur.lastrowid}"

    def _save_generic_result(self, task_id: str, result: dict) -> str:
        self._ensure_generic_table()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO task_results_generic (task_id, payload, created_at)"
                " VALUES (?, ?, ?)",
                (task_id, json.dumps(result, ensure_ascii=False), now_iso()),
            )
            return f"task_results_generic:{cur.lastrowid}"

    def _ensure_analysis_history_table(self):
        """Mirror of PortfolioDatabase.analysis_history schema — same file.

        Safe to call repeatedly thanks to IF NOT EXISTS + idempotent ALTERs.
        Having the schema here keeps TaskStore self-contained: TaskManager
        can save analysis results even before PortfolioDatabase has been
        initialized this process. The ALTER pass is the same shape as
        PortfolioDatabase._migrate_analysis_history so a worker process
        booting first doesn't leave a stripped-down table behind.
        """
        with self._lock, self._conn() as conn:
            conn.execute("""
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
                    created_by INTEGER,
                    provider TEXT,
                    config_hash TEXT,
                    task_id TEXT,
                    duration_sec REAL,
                    bookmarked INTEGER DEFAULT 0,
                    depth TEXT DEFAULT 'standard'
                )
            """)
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(analysis_history)"
            ).fetchall()}
            additions = [
                ("action", "TEXT"), ("confidence", "TEXT"),
                ("position_pct", "REAL"),
                ("entry_low", "REAL"), ("entry_high", "REAL"),
                ("stop_loss", "REAL"), ("take_profit", "REAL"),
                ("model", "TEXT"), ("steps_json", "TEXT"),
                ("created_by", "INTEGER"), ("provider", "TEXT"),
                ("config_hash", "TEXT"), ("task_id", "TEXT"),
                ("duration_sec", "REAL"),
                ("bookmarked", "INTEGER DEFAULT 0"),
                ("depth", "TEXT DEFAULT 'standard'"),
            ]
            for name, typ in additions:
                if name not in cols:
                    conn.execute(
                        f"ALTER TABLE analysis_history ADD COLUMN {name} {typ}"
                    )

    def _ensure_screen_table(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screen_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    market TEXT,
                    strategy TEXT,
                    results_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

    def _ensure_screen_v2_table(self):
        """Screener V2 results table — richer schema than V1."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screen_results_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    market TEXT,
                    strategy TEXT,
                    regime TEXT,
                    regime_confidence REAL,
                    enabled_gurus TEXT,
                    nl_query TEXT,
                    results_json TEXT NOT NULL,
                    universe_count INTEGER,
                    scored_count INTEGER,
                    final_count INTEGER,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screen_v2_created "
                "ON screen_results_v2(created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_screen_v2_task "
                "ON screen_results_v2(task_id)"
            )

    def save_screen_v2_result(
        self,
        task_id: str,
        market: str,
        strategy: str,
        result: dict,
        nl_query: str | None = None,
    ) -> int:
        """Persist a V2 screening run. Returns new row id."""
        import json as _json
        self._ensure_screen_v2_table()
        regime = result.get("regime") or {}
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO screen_results_v2
                   (task_id, market, strategy, regime, regime_confidence,
                    enabled_gurus, nl_query, results_json,
                    universe_count, scored_count, final_count,
                    duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, market, strategy,
                    regime.get("label"), regime.get("confidence"),
                    _json.dumps(result.get("enabled_gurus") or [], ensure_ascii=False),
                    nl_query,
                    _json.dumps(result, ensure_ascii=False),
                    result.get("universe_count"),
                    result.get("scored_count"),
                    result.get("final_count"),
                    result.get("duration_ms"),
                    now_iso(),
                ),
            )
            return cur.lastrowid

    def get_screen_v2_result(self, result_id: int) -> dict | None:
        """Get a V2 screen result by id."""
        self._ensure_screen_v2_table()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM screen_results_v2 WHERE id = ?", (result_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            import json as _json
            try:
                d["results"] = _json.loads(d.pop("results_json") or "{}")
            except Exception:
                d["results"] = {}
            try:
                d["enabled_gurus"] = _json.loads(d.get("enabled_gurus") or "[]")
            except Exception:
                d["enabled_gurus"] = []
            return d

    def list_screen_v2_history(self, limit: int = 50) -> list[dict]:
        """Lightweight list of past V2 runs (no full results_json)."""
        self._ensure_screen_v2_table()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, task_id, market, strategy, regime, regime_confidence,
                          universe_count, scored_count, final_count,
                          duration_ms, created_at
                   FROM screen_results_v2
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def _ensure_backtest_table(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    ticker TEXT,
                    strategy_id TEXT,
                    period TEXT,
                    initial_capital REAL,
                    metrics_json TEXT,
                    equity_curve_json TEXT,
                    trades_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

    def _ensure_generic_table(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_results_generic (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    payload TEXT,
                    created_at TEXT NOT NULL
                )
            """)

    # ── Maintenance ──────────────────────────────────────────────────────

    def cleanup_expired(self, days: int = 30) -> int:
        """Delete task rows older than *days*. Returns rows deleted."""
        cutoff = (datetime.now() - timedelta(days=max(0, days))) \
            .strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM tasks WHERE created_at < ?", (cutoff,)
            )
            return cur.rowcount

    def mark_orphaned_running_as_failed(self, reason: str = "服务中断") -> int:
        """Call on startup — any task still `running` is from a crashed process."""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status = 'failed', error_message = ?,"
                " completed_at = ? WHERE status IN ('running', 'pending')",
                (reason, now_iso()),
            )
            return cur.rowcount

    def count_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()
            return {r["status"]: r["n"] for r in rows}
