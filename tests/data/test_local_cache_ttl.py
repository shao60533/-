"""hardening-iteration-v1 P2.1 + P2.2 + P2.3 — LocalCache hardening.

Pre-P2.1: ``LocalCache.set`` did not accept a ``ttl=`` kwarg; v3 guru
cache passed it and crashed inside a swallowed except, so the cache hit
rate stayed at 0% silently. Pre-P2.2: unknown categories silently
inherited "no TTL = forever". Pre-P2.3: payloads were ``pickle.dumps``
→ read path was an RCE surface for anything that could write to
``cache.db`` (Railway volume, host fs, malicious commit).

This suite locks down:
    P2.1: set(category, key, value, ttl=N) accepted; per-entry TTL
          override drives expiry decisions.
    P2.2: unknown categories rejected; ``unsafe_default_ttl=N`` opts
          in dev categories at runtime; registered v3 categories
          accept writes.
    P2.3: payloads are JSON-envelope, not pickle. DataFrames round-trip
          via to_json/read_json. Legacy pickle blobs are rejected at
          read (returned as cache miss) AND purged by
          migrate_drop_legacy_pickle().
"""

from __future__ import annotations

import pickle
import sqlite3
import time
from pathlib import Path

import pytest

from stock_trading_system.data.local_cache import (
    LocalCache, _DEFAULT_TTL, _ENVELOPE_VERSION, _serialize, _deserialize,
)


@pytest.fixture
def cache(tmp_path):
    return LocalCache(str(tmp_path / "cache.db"))


# ── P2.1: ttl kwarg accepted + honored ─────────────────────────────────────


def test_set_accepts_ttl_kwarg(cache):
    """The v3-guru caller pattern: ttl=<seconds>."""
    # Should NOT raise TypeError as the pre-P2.1 signature did.
    cache.set("price_quote", "AAPL", {"last": 150.0}, ttl=60)
    assert cache.get("price_quote", "AAPL") == {"last": 150.0}


def test_per_entry_ttl_overrides_category_default(cache):
    """ttl=1 second on a category with 60s default → entry should expire
    after 1.1 seconds (or rather, the category default is irrelevant)."""
    cache.set("price_quote", "TINY_TTL", {"v": 1}, ttl=1)
    # immediately readable
    assert cache.get("price_quote", "TINY_TTL") == {"v": 1}
    time.sleep(1.2)
    assert cache.get("price_quote", "TINY_TTL") is None


def test_no_ttl_falls_back_to_category_default(cache):
    """Without explicit ttl, set uses _DEFAULT_TTL[category]."""
    cache.set("price_quote", "DEFAULT", {"v": 2})
    assert cache.get("price_quote", "DEFAULT") == {"v": 2}
    # price_quote default is 60s; entry is still fresh.


# ── P2.2: unknown category rejected ───────────────────────────────────────


def test_unknown_category_rejected(cache, caplog):
    """set() into an unregistered category is a no-op + warning."""
    with caplog.at_level("WARNING"):
        cache.set("ghost_category", "k", "v")
    # No row should have been written.
    assert cache.get("ghost_category", "k") is None
    assert any("unknown category" in r.message.lower() for r in caplog.records)


def test_unsafe_default_ttl_opts_in_category(cache):
    """Caller can register dev/experimental categories at runtime."""
    cache.set("dev_temp", "k", {"value": 42}, unsafe_default_ttl=10)
    assert cache.get("dev_temp", "k") == {"value": 42}


def test_registered_v3_categories_accept_writes(cache):
    """P2.2 added guru_signal_v3 / regime / nl_parse / roundtable.
    Each should accept writes without unsafe_default_ttl."""
    for cat in ("guru_signal_v3", "regime", "nl_parse", "roundtable"):
        cache.set(cat, "k", {"cat": cat})
        assert cache.get(cat, "k") == {"cat": cat}


# ── P2.2 default-ttl table coverage ────────────────────────────────────────


def test_default_ttl_table_includes_v3_categories():
    """Defensive: _DEFAULT_TTL is the canonical registry, and the v3
    categories must always live here so deployments don't lose hits
    when a new node spins up without the runtime dev-register call."""
    for cat in ("guru_signal_v3", "regime", "nl_parse", "roundtable"):
        assert cat in _DEFAULT_TTL, f"missing v3 category {cat!r} in _DEFAULT_TTL"


# ── P2.3 [H10]: JSON payload, no pickle ─────────────────────────────────────


def test_serialize_json_envelope_for_plain_dict():
    """JSON-able values land inside the tagged envelope."""
    blob = _serialize({"last": 150.0, "volume": 1_000_000})
    # Must start with the JSON header byte (used as the "is this safe to
    # parse" gate at read time).
    assert blob.startswith(b"{")
    import json as _json
    env = _json.loads(blob.decode("utf-8"))
    assert env == {"v": _ENVELOPE_VERSION, "kind": "json",
                    "data": {"last": 150.0, "volume": 1_000_000}}


def test_deserialize_round_trip_dict():
    blob = _serialize({"x": [1, 2, 3], "y": "text"})
    assert _deserialize(blob) == {"x": [1, 2, 3], "y": "text"}


def test_dataframe_round_trip(cache):
    """pandas DataFrames round-trip via to_json(orient='split')."""
    pd = pytest.importorskip("pandas")
    df_in = pd.DataFrame(
        {"open": [100.0, 101.0], "close": [100.5, 102.0]},
        index=pd.to_datetime(["2026-05-01", "2026-05-02"]),
    )
    cache.set_bars("AAPL", "1mo", "1d", df_in)
    df_out = cache.get_bars("AAPL", "1mo", "1d")
    assert df_out is not None
    # Compare shape + content; index dtype may shift after JSON round-trip.
    assert list(df_out.columns) == ["open", "close"]
    assert df_out["close"].tolist() == [100.5, 102.0]


def test_legacy_pickle_blob_is_rejected_as_miss(tmp_path):
    """Hand-write a pickle row, then verify the cache treats it as a
    miss instead of unpickling. This is the H10 closure."""
    db_path = str(tmp_path / "cache.db")
    # Create the table by constructing a LocalCache once (also runs the
    # auto-migration but the pickle row hasn't been inserted yet).
    LocalCache(db_path)
    # Inject a pickle row manually, bypassing LocalCache.set.
    conn = sqlite3.connect(db_path)
    pickle_blob = pickle.dumps({"evil": "payload"})
    conn.execute(
        "INSERT OR REPLACE INTO kv_cache (category, key, payload, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        ("price_quote", "ATTACKER",
         pickle_blob, time.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()

    # Re-open via LocalCache — _init() will purge the legacy row.
    cache2 = LocalCache(db_path)
    assert cache2.get("price_quote", "ATTACKER") is None
    # And the row is gone, not just hidden.
    conn = sqlite3.connect(db_path)
    cnt = conn.execute(
        "SELECT COUNT(*) FROM kv_cache WHERE key = 'ATTACKER'"
    ).fetchone()[0]
    conn.close()
    assert cnt == 0


def test_migrate_drop_legacy_pickle_is_idempotent(tmp_path):
    """Running the migration twice is a no-op after the first pass."""
    db_path = str(tmp_path / "cache.db")
    cache = LocalCache(db_path)
    # First call: nothing to drop (fresh DB).
    assert cache.migrate_drop_legacy_pickle() == 0
    # Write a JSON row.
    cache.set("price_quote", "AAPL", {"last": 1.0})
    # Migration should leave JSON rows alone.
    assert cache.migrate_drop_legacy_pickle() == 0
    assert cache.get("price_quote", "AAPL") == {"last": 1.0}


def test_no_pickle_call_in_local_cache_module():
    """Defensive: H10 RCE surface comes from active ``pickle.loads(...)``
    or ``pickle.dumps(...)`` calls. Verify they've been removed so future
    edits don't reintroduce them (docstrings referring to the old
    behaviour are allowed)."""
    import re
    from stock_trading_system.data import local_cache as lc_mod
    src = Path(lc_mod.__file__).read_text(encoding="utf-8")
    # Match active call sites only: ``pickle.loads(`` / ``pickle.dumps(``
    # with an opening paren immediately after — that's a function call,
    # not a doc reference.
    assert not re.search(r"pickle\.loads\s*\(", src), \
        "P2.3 regression: pickle.loads(...) call back in local_cache.py"
    assert not re.search(r"pickle\.dumps\s*\(", src), \
        "P2.3 regression: pickle.dumps(...) call back in local_cache.py"
