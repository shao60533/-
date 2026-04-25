"""Unified SQLite-backed cache for price / fundamentals / news / bars.

Design goals:
- Single cache class with typed accessors (set_price, get_price, ...)
- Per-category TTL, configurable via `config["data_routing"]["cache_ttl"]`.
- Stores pickled payload for flexibility (DataFrame, dict, list all work).
- Thread-safe short-lived connections + WAL mode.
"""

from __future__ import annotations

import pickle
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stock_trading_system.utils import get_logger

logger = get_logger("data.cache")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv_cache (
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    payload BLOB NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (category, key)
);

CREATE INDEX IF NOT EXISTS idx_cache_fetched_at ON kv_cache(fetched_at);
"""


# Default TTLs in seconds — overridden by config[data_routing][cache_ttl].
_DEFAULT_TTL: dict[str, int] = {
    "price_quote": 60,        # 1 min
    "daily_bars": 43200,      # 12 h
    "minute_bars": 300,       # 5 min
    "fundamentals": 86400,    # 24 h
    "news": 3600,             # 1 h
    "screen_results": 3600,   # 1 h
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


class LocalCache:
    """SQLite-backed cache with per-category TTLs."""

    def __init__(self, db_path: str, config: dict | None = None):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        ttl_overrides = {}
        if config:
            ttl_overrides = (
                config.get("data_routing", {}).get("cache_ttl", {}) or {}
            )
        self._ttl = {**_DEFAULT_TTL, **{k: int(v) for k, v in ttl_overrides.items()}}

        # Stats (process-local, for monitoring cache hit rate)
        self._hits = 0
        self._misses = 0

        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── Generic get/set ──────────────────────────────────────────────────

    def get(self, category: str, key: str) -> Any | None:
        """Return cached value if present and not expired. None otherwise."""
        ttl = self._ttl.get(category)
        if ttl is None:
            # Unknown category — treat as infinite TTL but warn.
            logger.debug("Unknown cache category '%s' — using no TTL", category)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at FROM kv_cache "
                "WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()
        if not row:
            self._misses += 1
            return None
        if ttl is not None:
            try:
                fetched = _parse(row["fetched_at"])
                if datetime.now() - fetched > timedelta(seconds=ttl):
                    self._misses += 1
                    return None
            except ValueError:
                self._misses += 1
                return None
        try:
            value = pickle.loads(row["payload"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to unpickle %s:%s — %s", category, key, e)
            self._misses += 1
            return None
        self._hits += 1
        return value

    def set(self, category: str, key: str, value: Any) -> None:
        """Write/overwrite a cache entry."""
        try:
            blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            logger.warning("Cannot pickle %s:%s — %s", category, key, e)
            return
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO kv_cache (category, key, payload, fetched_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(category, key) DO UPDATE SET "
                "  payload = excluded.payload, fetched_at = excluded.fetched_at",
                (category, key, blob, _now()),
            )

    def delete(self, category: str, key: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM kv_cache WHERE category = ? AND key = ?",
                (category, key),
            )
            return cur.rowcount > 0

    # ── Typed helpers ────────────────────────────────────────────────────

    def get_price(self, ticker: str) -> dict | None:
        return self.get("price_quote", ticker.upper())

    def set_price(self, ticker: str, quote: dict) -> None:
        self.set("price_quote", ticker.upper(), quote)

    def get_fundamentals(self, ticker: str) -> dict | None:
        return self.get("fundamentals", ticker.upper())

    def set_fundamentals(self, ticker: str, data: dict) -> None:
        self.set("fundamentals", ticker.upper(), data)

    def get_news(self, ticker: str) -> list[dict] | None:
        return self.get("news", ticker.upper())

    def set_news(self, ticker: str, news: list[dict]) -> None:
        self.set("news", ticker.upper(), news)

    def get_bars(self, ticker: str, period: str, interval: str) -> Any | None:
        category = "minute_bars" if interval.endswith("m") or interval.endswith("h") \
            else "daily_bars"
        return self.get(category, f"{ticker.upper()}|{period}|{interval}")

    def set_bars(self, ticker: str, period: str, interval: str, df: Any) -> None:
        category = "minute_bars" if interval.endswith("m") or interval.endswith("h") \
            else "daily_bars"
        self.set(category, f"{ticker.upper()}|{period}|{interval}", df)

    # ── Maintenance & stats ──────────────────────────────────────────────

    def cleanup(self) -> int:
        """Delete all expired entries based on per-category TTLs."""
        total = 0
        now = datetime.now()
        with self._lock, self._conn() as conn:
            for category, ttl in self._ttl.items():
                cutoff = (now - timedelta(seconds=ttl)).strftime("%Y-%m-%d %H:%M:%S")
                cur = conn.execute(
                    "DELETE FROM kv_cache WHERE category = ? AND fetched_at < ?",
                    (category, cutoff),
                )
                total += cur.rowcount
        return total

    def clear(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM kv_cache")

    def stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total else 0.0
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM kv_cache").fetchone()
            entries = row["n"] if row else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "entries": entries,
        }

    def ttl_for(self, category: str) -> int | None:
        return self._ttl.get(category)
