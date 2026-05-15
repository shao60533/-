"""Unified SQLite-backed cache for price / fundamentals / news / bars.

hardening-iteration-v1 P2.3 [H10]: payloads are JSON now, not pickle.
Pre-P2.3 the cache deserialized untrusted blobs with ``pickle.loads`` —
any process that could write to ``cache.db`` (Railway volume, host
filesystem, malicious git commit) could trigger arbitrary code at
read time. JSON serialisation removes that RCE surface.

DataFrames (the one non-JSON-native shape we store) round-trip via
``df.to_json(orient="split")`` inside a tagged envelope:

    {"v": 1, "kind": "df", "data": "<orient=split JSON string>"}

Plain values land as:

    {"v": 1, "kind": "json", "data": <inner>}

Legacy pickle rows are recognised by the absence of the JSON header
byte ``{``; they're read-skipped (returning a cache miss) so the next
write rotates them. A one-shot ``migrate_drop_legacy_pickle()`` helper
purges them eagerly.

Design goals:
- Single cache class with typed accessors (set_price, get_price, ...)
- Per-category TTL, configurable via `config["data_routing"]["cache_ttl"]`.
- Stores JSON payload (was: pickle); DataFrame round-tripped via
  pandas to_json(orient="split").
- Thread-safe short-lived connections + WAL mode.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from stock_trading_system.utils.timez import now_local
from io import StringIO
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
#
# hardening-iteration-v1 P2.2: every category that downstream code may
# write MUST be registered here, otherwise set() rejects the write. This
# closes the pre-P2.2 hole where unknown categories silently became
# "no-TTL = forever" — turning the cache into a memory-leaking time bomb.
_DEFAULT_TTL: dict[str, int] = {
    "price_quote": 60,        # 1 min
    "daily_bars": 43200,      # 12 h
    "minute_bars": 300,       # 5 min
    "fundamentals": 86400,    # 24 h
    "news": 3600,             # 1 h
    "screen_results": 3600,   # 1 h
    # screener v3 guru signals — TTL is computed per-call via
    # _seconds_until_end_of_day(), so the entry here is just to
    # register the category (any positive number works as default).
    "guru_signal_v3": 3600,
    # screener v2 metadata caches
    "regime": 3600,           # market regime detection (refresh hourly)
    "nl_parse": 86400,        # NL → query spec (deterministic, day-long)
    "roundtable": 3600,       # v3 roundtable consensus
}


# Envelope schema version. Bump if the on-disk shape changes; readers
# must reject envelopes with unknown ``v`` rather than guess.
_ENVELOPE_VERSION = 1


def _now() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _serialize(value: Any) -> bytes:
    """Wrap ``value`` in the JSON envelope and return UTF-8 bytes."""
    try:
        import pandas as pd
    except ImportError:  # pandas absent → df path is unreachable
        pd = None

    if pd is not None and isinstance(value, pd.DataFrame):
        envelope = {
            "v": _ENVELOPE_VERSION,
            "kind": "df",
            "data": value.to_json(orient="split", date_format="iso"),
        }
    else:
        envelope = {"v": _ENVELOPE_VERSION, "kind": "json", "data": value}
    return json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")


def _deserialize(blob: bytes) -> Any:
    """Inverse of :func:`_serialize`. Returns None for unknown / legacy
    payloads so the cache treats them as misses and rewrites on next set."""
    if not blob:
        return None
    # Legacy pickle blobs start with the pickle opcode \x80 (binary
    # protocol) — never a printable JSON char. Reject them outright
    # so we can't accidentally trip a pickle gadget chain.
    if not blob.startswith(b"{"):
        return None
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict) or envelope.get("v") != _ENVELOPE_VERSION:
        return None
    kind = envelope.get("kind")
    if kind == "json":
        return envelope.get("data")
    if kind == "df":
        try:
            import pandas as pd
        except ImportError:
            return None
        raw = envelope.get("data")
        if not isinstance(raw, str):
            return None
        try:
            return pd.read_json(StringIO(raw), orient="split")
        except ValueError:
            return None
    return None


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

        # Per-entry TTL overrides for callers that need finer control than
        # the category default (e.g. screener v3 guru cache: "expire at
        # end of trading day"). Process-local; LRU-bounded so a busy
        # cache doesn't grow this dict unbounded.
        self._per_entry_ttl: dict[tuple[str, str], int] = {}

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
        # hardening-iteration-v1 P2.3 [H10]: drop legacy pickle rows on
        # first boot. Idempotent — next boots see an empty result.
        self.migrate_drop_legacy_pickle()

    # ── Generic get/set ──────────────────────────────────────────────────

    def get(self, category: str, key: str) -> Any | None:
        """Return cached value if present and not expired. None otherwise.

        TTL resolution: per-entry override (set via ``set(..., ttl=)``) >
        category default in ``_DEFAULT_TTL`` > None (read-only treat as
        non-expiring). The per-entry path is what makes screener v3
        guru's "expire at EOD" semantics work.
        """
        ttl = self._per_entry_ttl.get((category, key))
        if ttl is None:
            ttl = self._ttl.get(category)
        if ttl is None:
            # Unknown category at read time — likely legacy row from a
            # category we since un-registered. Treat as non-expiring so
            # we don't lose data, but log for visibility.
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
                if now_local() - fetched > timedelta(seconds=ttl):
                    self._misses += 1
                    return None
            except ValueError:
                self._misses += 1
                return None
        value = _deserialize(row["payload"])
        if value is None:
            # Legacy pickle row, malformed JSON envelope, or genuinely-
            # stored None. We can't distinguish "real None" from
            # "rejected blob" here, so treat the entry as a miss — the
            # caller will refetch and overwrite. Safer than silently
            # returning stale data.
            self._misses += 1
            return None
        self._hits += 1
        return value

    def set(
        self,
        category: str,
        key: str,
        value: Any,
        ttl: int | None = None,
        unsafe_default_ttl: int | None = None,
    ) -> None:
        """Write/overwrite a cache entry.

        ``ttl`` is accepted for callers that want a per-write TTL override
        (e.g. screener v3 guru cache computes "seconds until EOD"). When
        provided it shadows ``_DEFAULT_TTL[category]`` for THIS entry's
        eligibility check at read time. The current schema doesn't store
        per-entry TTL, so the override is applied logically via
        ``self._per_entry_ttl[(cat,key)]`` — see ``get()``.

        hardening-iteration-v1 P2.1: pre-P2.1 LocalCache.set didn't
        accept ``ttl=`` at all and every v3 guru cache write raised
        ``TypeError`` that was swallowed in caller's debug-only except,
        so cache hit-rate was 0% silently. This signature unblocks v3.

        hardening-iteration-v1 P2.2: unknown categories are rejected
        (was: silently treated as "no TTL = forever"). Use
        ``unsafe_default_ttl`` to opt-in for dev/experimental categories
        before they're registered in ``_DEFAULT_TTL``.

        hardening-iteration-v1 P2.3: values are JSON-encoded inside a
        tagged envelope; DataFrame round-trips via ``to_json/read_json``.
        Was: ``pickle.dumps`` — read path was an RCE surface.
        """
        if category not in self._ttl:
            if unsafe_default_ttl is None:
                logger.warning(
                    "LocalCache.set rejected: unknown category %r — "
                    "register it in _DEFAULT_TTL first or pass "
                    "unsafe_default_ttl=<seconds> for experimental use",
                    category,
                )
                return
            # Caller knows what they're doing — register the category
            # for the lifetime of this LocalCache instance.
            self._ttl[category] = int(unsafe_default_ttl)
            logger.info("LocalCache: dev-registered category %r ttl=%ds",
                         category, unsafe_default_ttl)

        try:
            blob = _serialize(value)
        except (TypeError, ValueError) as e:
            # Non-JSONable Python objects (custom classes, sets, ...)
            # land here. Same outcome as the pre-P2.3 pickle failure —
            # write is dropped + warning logged.
            logger.warning("Cannot json-encode %s:%s — %s", category, key, e)
            return
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO kv_cache (category, key, payload, fetched_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(category, key) DO UPDATE SET "
                "  payload = excluded.payload, fetched_at = excluded.fetched_at",
                (category, key, blob, _now()),
            )
        if ttl is not None:
            self._per_entry_ttl[(category, key)] = int(ttl)

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
        now = now_local()
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

    def migrate_drop_legacy_pickle(self) -> int:
        """Delete rows whose payload doesn't start with the JSON header
        byte ``{`` — legacy pickle blobs from before P2.3. Returns the
        number of rows removed. Safe to run repeatedly; idempotent."""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM kv_cache WHERE substr(payload, 1, 1) != ?",
                (b"{",),
            )
            n = cur.rowcount
        if n:
            logger.info("LocalCache: dropped %d legacy pickle row(s) "
                         "(hardening-iteration-v1 P2.3 [H10])", n)
        return n

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
