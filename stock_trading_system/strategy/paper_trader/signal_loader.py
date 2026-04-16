"""Load AI analysis signals from analysis_history for paper-trade replay."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.signals")


class SignalLoader:
    """Read signals from analysis_history, parse advice_json."""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def load(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        tickers: list[str] | None = None,
        signals: list[str] | None = None,
    ) -> list[dict]:
        """Return list of signal dicts, ordered by analysis date ascending.

        Each signal contains:
            analysis_id, ticker, date, signal, advice, created_at
        """
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

        sql = f"""SELECT id, ticker, date, signal, advice_json, created_at
                  FROM analysis_history
                  WHERE {' AND '.join(where)}
                  ORDER BY date ASC, id ASC"""
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        out = []
        for r in rows:
            advice = {}
            if r["advice_json"]:
                try:
                    advice = json.loads(r["advice_json"])
                except (json.JSONDecodeError, TypeError):
                    advice = {}
            out.append({
                "analysis_id": r["id"],
                "ticker": r["ticker"],
                "date": r["date"],
                "signal": r["signal"],
                "advice": advice,
                "created_at": r["created_at"],
            })
        logger.info("SignalLoader: %d signals (start=%s end=%s)", len(out), start_date, end_date)
        return out

    def get_one(self, analysis_id: int) -> dict | None:
        """Load one analysis by id (for auto-track path)."""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT id, ticker, date, signal, advice_json, created_at "
                "FROM analysis_history WHERE id = ?",
                (analysis_id,),
            ).fetchone()
        if not r:
            return None
        advice = {}
        if r["advice_json"]:
            try:
                advice = json.loads(r["advice_json"])
            except Exception:
                pass
        return {
            "analysis_id": r["id"],
            "ticker": r["ticker"],
            "date": r["date"],
            "signal": r["signal"],
            "advice": advice,
            "created_at": r["created_at"],
        }
