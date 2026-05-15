"""Single source of truth for the ``analysis_history`` table schema.

hardening-iteration-v1 P3.5: pre-P3.5 the same CREATE TABLE statement
lived in two places — ``PortfolioDatabase._init_tables`` and
``TaskStore._ensure_analysis_history_table`` — and they drifted
(task_store missed the ``rendering_status`` / ``rendering_error`` /
``rendering_generated_at`` columns at the top-level CREATE; it relied on
the ALTER drift-fix loop to add them after the fact, which means a
race-conditioned worker process that booted FIRST left those columns
unindexed).

The CREATE statement + the canonical ALTER list now live here. Both
``PortfolioDatabase`` and ``TaskStore`` ``ensure_analysis_history(conn)``
through this module — drift is impossible.
"""

from __future__ import annotations

import sqlite3


CREATE_TABLE = """
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
    rendering_status TEXT DEFAULT 'pending',
    rendering_error TEXT,
    rendering_generated_at TEXT,
    created_by INTEGER,
    provider TEXT,
    config_hash TEXT,
    task_id TEXT,
    duration_sec REAL,
    bookmarked INTEGER DEFAULT 0,
    depth TEXT DEFAULT 'standard'
);
"""

# Each entry is (column_name, type_with_optional_default). The runner
# iterates and ALTERs anything missing. Keep in lockstep with the
# CREATE statement above — every column listed in CREATE must also
# appear here so existing tables get retro-fitted.
ALTERS: list[tuple[str, str]] = [
    ("action", "TEXT"),
    ("confidence", "TEXT"),
    ("position_pct", "REAL"),
    ("entry_low", "REAL"),
    ("entry_high", "REAL"),
    ("stop_loss", "REAL"),
    ("take_profit", "REAL"),
    ("model", "TEXT"),
    ("steps_json", "TEXT"),
    ("rendering_json", "TEXT"),
    ("rendering_status", "TEXT DEFAULT 'pending'"),
    ("rendering_error", "TEXT"),
    ("rendering_generated_at", "TEXT"),
    ("created_by", "INTEGER"),
    ("provider", "TEXT"),
    ("config_hash", "TEXT"),
    ("task_id", "TEXT"),
    ("duration_sec", "REAL"),
    ("bookmarked", "INTEGER DEFAULT 0"),
    ("depth", "TEXT DEFAULT 'standard'"),
]


def ensure_analysis_history(conn: sqlite3.Connection) -> None:
    """Create the table if missing + ALTER any missing columns onto
    an existing table. Idempotent and concurrency-safe — multiple
    processes can call this simultaneously and one of them wins each
    column add."""
    conn.execute(CREATE_TABLE)
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(analysis_history)"
    ).fetchall()}
    for name, typ in ALTERS:
        if name not in cols:
            try:
                conn.execute(
                    f"ALTER TABLE analysis_history ADD COLUMN {name} {typ}"
                )
            except sqlite3.OperationalError:
                # Race: another writer added the same column between
                # our PRAGMA snapshot and the ALTER. Safe to swallow.
                pass
