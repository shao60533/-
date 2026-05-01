"""Load AI analysis signals — primary source: ``user_analysis_advice`` (per-user).

v1.13 split holdings-aware advice off of the shared ``analysis_history`` row
and into ``user_analysis_advice`` (per (user, analysis) tuple), nulling
``analysis_history.advice_json`` for everyone except the original creator.
This module reflects that split:

* primary: read advice from ``user_analysis_advice`` for the requesting user
* legacy fallback: ``analysis_history.advice_json`` is read ONLY when the
  reader is the original creator OR the caller explicitly opts in via
  ``allow_legacy_no_user=True`` (used by global backfill tools that have
  no user context).

When neither path produces advice we return an empty dict — never the
shared ``advice_json`` of another user.
"""

from __future__ import annotations

import json
import sqlite3

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.signals")


def _normalize_advice(adv: dict) -> dict:
    """Emit both key spellings so downstream plan_parser code that prefers
    either ``suggested_position_pct``/``position_pct`` or
    ``entry_price_low``/``entry_low`` works without coupling.
    """
    if not adv:
        return {}
    out = dict(adv)
    if "position_pct" in out and "suggested_position_pct" not in out:
        out["suggested_position_pct"] = out["position_pct"]
    if "suggested_position_pct" in out and "position_pct" not in out:
        out["position_pct"] = out["suggested_position_pct"]
    for canon, alias in (("entry_low", "entry_price_low"),
                         ("entry_high", "entry_price_high")):
        if canon in out and alias not in out:
            out[alias] = out[canon]
        if alias in out and canon not in out:
            out[canon] = out[alias]
    return out


class SignalLoader:
    """Read signals from analysis_history; resolve advice per-user."""

    def __init__(self, db_path: str, user_id: int | None = None,
                 allow_legacy_no_user: bool = False):
        self._db_path = str(db_path)
        self._user_id = user_id
        self._allow_legacy_no_user = allow_legacy_no_user

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _resolve_advice(self, conn: sqlite3.Connection, analysis_id: int,
                         created_by, user_id: int | None) -> dict:
        # 1) Primary — user_analysis_advice for the requesting user.
        if user_id is not None:
            r = conn.execute(
                "SELECT * FROM user_analysis_advice "
                "WHERE user_id = ? AND analysis_id = ?",
                (int(user_id), int(analysis_id)),
            ).fetchone()
            if r:
                d = {k: r[k] for k in r.keys()
                     if k not in ("id", "user_id", "analysis_id",
                                  "holdings_context_snapshot", "created_at")}
                return _normalize_advice(d)
        # 2) Legacy fallback — only the original creator may read advice_json.
        is_creator = (
            user_id is not None and created_by is not None
            and int(created_by) == int(user_id)
        )
        no_user_allowed = (user_id is None and self._allow_legacy_no_user)
        if not (is_creator or no_user_allowed):
            return {}
        r = conn.execute(
            "SELECT advice_json FROM analysis_history WHERE id = ?",
            (int(analysis_id),),
        ).fetchone()
        if not r or not r["advice_json"]:
            return {}
        try:
            return _normalize_advice(json.loads(r["advice_json"]) or {})
        except (json.JSONDecodeError, TypeError):
            return {}

    def load(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
        signals: list[str] | None = None,
        user_id: int | None = None,
    ) -> list[dict]:
        """Return list of signal dicts ordered by analysis date ascending.

        Each signal contains:
            ``analysis_id``, ``ticker``, ``date``, ``signal``, ``advice``,
            ``created_at``, ``created_by``.
        """
        uid = user_id if user_id is not None else self._user_id
        where = ["signal != 'ERROR'"]
        params: list = []
        if start_date:
            where.append("date >= ?")
            params.append(start_date)
        if end_date:
            where.append("date <= ?")
            params.append(end_date)
        if tickers:
            placeholders = ",".join("?" * len(tickers))
            where.append(f"ticker IN ({placeholders})")
            params.extend([t.upper() for t in tickers])
        if signals:
            placeholders = ",".join("?" * len(signals))
            where.append(f"signal IN ({placeholders})")
            params.extend([s.upper() for s in signals])

        sql = (
            f"SELECT id, ticker, date, signal, created_by, created_at "
            f"FROM analysis_history WHERE {' AND '.join(where)} "
            f"ORDER BY date ASC, id ASC"
        )
        out: list[dict] = []
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            for r in rows:
                advice = self._resolve_advice(conn, r["id"], r["created_by"], uid)
                out.append({
                    "analysis_id": r["id"],
                    "ticker": r["ticker"],
                    "date": r["date"],
                    "signal": r["signal"],
                    "advice": advice,
                    "created_at": r["created_at"],
                    "created_by": r["created_by"],
                })
        logger.info("SignalLoader: %d signals (user_id=%s)", len(out), uid)
        return out

    def get_one(self, analysis_id: int,
                user_id: int | None = None) -> dict | None:
        """Load one analysis by id (for auto-track path)."""
        uid = user_id if user_id is not None else self._user_id
        with self._conn() as conn:
            r = conn.execute(
                "SELECT id, ticker, date, signal, created_by, created_at "
                "FROM analysis_history WHERE id = ?",
                (int(analysis_id),),
            ).fetchone()
            if not r:
                return None
            advice = self._resolve_advice(conn, r["id"], r["created_by"], uid)
        return {
            "analysis_id": r["id"],
            "ticker": r["ticker"],
            "date": r["date"],
            "signal": r["signal"],
            "advice": advice,
            "created_at": r["created_at"],
            "created_by": r["created_by"],
        }

    def backfill_all(self, user_id: int | None = None) -> list[dict]:
        return self.load(user_id=user_id)
