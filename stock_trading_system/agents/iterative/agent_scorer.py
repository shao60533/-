"""Agent Scorer — per-agent signal tracking and performance metrics.

Records each agent's directional call after every analysis, then
back-fills realized returns and computes rolling Sharpe ratios so
the Darwinian weight system can promote/demote agents.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from stock_trading_system.agents.iterative.config import IterationConfig
from stock_trading_system.agents.iterative.signal_extractor import (
    extract_signal_fixed,
    extract_signal_llm,
    extract_signal_regex,
)
from stock_trading_system.utils import get_logger

logger = get_logger("iterative.agent_scorer")

# Map of the 7 tracked agents → how to extract their signal from final_state.
# format: {agent_id: (state_key, extraction_method)}
#   extraction_method: "llm" | "fixed" | "regex"
AGENT_MAP: dict[str, tuple[str, str]] = {
    "market_analyst":       ("market_report",       "llm"),
    "sentiment_analyst":    ("sentiment_report",    "llm"),
    "news_analyst":         ("news_report",         "llm"),
    "fundamentals_analyst": ("fundamentals_report", "llm"),
    "bull_researcher":      ("investment_debate_state", "fixed"),
    "bear_researcher":      ("investment_debate_state", "fixed"),
    "trader":               ("trader_investment_plan",  "regex"),
}


class AgentScorer:
    """Records per-agent signals and computes rolling performance metrics."""

    def __init__(self, db_path: str, config: IterationConfig,
                 llm_call: callable | None = None):
        """
        Args:
            db_path: Path to the SQLite database.
            config: Iteration configuration.
            llm_call: Optional callable(system_prompt, user_prompt) -> str
                      for LLM-based signal extraction.
        """
        self._db_path = db_path
        self._config = config
        self._llm_call = llm_call
        self._ensure_weights_table()
        # Load weights from DB, fall back to 1.0 for missing agents
        self._weights: dict[str, float] = {aid: 1.0 for aid in AGENT_MAP}
        self._weights.update(self._load_weights_from_db())

    def _ensure_weights_table(self):
        """Create agent_weights table if not exists."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_weights (
                agent_id TEXT PRIMARY KEY,
                weight REAL NOT NULL DEFAULT 1.0,
                updated_at TEXT,
                updated_by_task_id TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _load_weights_from_db(self) -> dict[str, float]:
        conn = self._get_conn()
        rows = conn.execute("SELECT agent_id, weight FROM agent_weights").fetchall()
        conn.close()
        return {r["agent_id"]: r["weight"] for r in rows}

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Record signals ────────────────────────────────────────────────

    def record_analysis(
        self,
        analysis_id: int,
        ticker: str,
        date: str,
        final_state: dict[str, Any],
        price_at_call: float | None,
    ) -> list[dict]:
        """Extract and persist signals for all 7 agents from a completed analysis.

        Returns list of inserted scorecard dicts (for testing / logging).
        """
        if not self._config.scorer.extract_signals:
            return []

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records: list[dict] = []

        for agent_id, (state_key, method) in AGENT_MAP.items():
            signal = self._extract_signal(agent_id, state_key, method, final_state)
            if signal == "ERROR":
                logger.warning("Skipping scorecard for %s — extraction failed", agent_id)
                continue

            record = {
                "analysis_id": analysis_id,
                "agent_id": agent_id,
                "ticker": ticker,
                "date": date,
                "signal": signal,
                "price_at_call": price_at_call,
                "created_at": now,
            }
            records.append(record)

        if records:
            self._insert_scorecards(records)
            logger.info("Recorded %d agent scorecards for analysis %d (%s)",
                        len(records), analysis_id, ticker)
        return records

    def _extract_signal(
        self, agent_id: str, state_key: str, method: str,
        final_state: dict[str, Any],
    ) -> str:
        if method == "fixed":
            return extract_signal_fixed(agent_id)

        raw_value = final_state.get(state_key, "")
        if method == "regex":
            text = raw_value if isinstance(raw_value, str) else str(raw_value)
            return extract_signal_regex(text)

        # method == "llm"
        text = raw_value if isinstance(raw_value, str) else str(raw_value)
        if self._llm_call is None:
            logger.warning("No LLM callable — falling back to NEUTRAL for %s", agent_id)
            return "NEUTRAL"
        return extract_signal_llm(text, self._llm_call)

    def _insert_scorecards(self, records: list[dict]) -> None:
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO agent_scorecards
                   (analysis_id, agent_id, ticker, date, signal,
                    price_at_call, created_at)
                   VALUES (:analysis_id, :agent_id, :ticker, :date,
                           :signal, :price_at_call, :created_at)""",
                records,
            )

    # ── Back-fill returns ─────────────────────────────────────────────

    def backfill_returns(self, get_price: callable) -> int:
        """Back-fill 5d and 20d returns for scorecards that have a price_at_call
        but no return_5d yet.

        Args:
            get_price: callable(ticker) -> dict with 'last' or 'close' key.

        Returns:
            Number of rows updated.
        """
        updated = 0
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, ticker, date, signal, price_at_call
                   FROM agent_scorecards
                   WHERE return_5d IS NULL AND price_at_call IS NOT NULL"""
            ).fetchall()

            for row in rows:
                row_dict = dict(row)
                try:
                    call_date = datetime.strptime(row_dict["date"], "%Y-%m-%d")
                except ValueError:
                    continue

                price_at_call = row_dict["price_at_call"]
                if not price_at_call or price_at_call <= 0:
                    continue

                # Check if enough time has passed for 5d backfill
                days_elapsed = (datetime.now() - call_date).days
                if days_elapsed < 5:
                    continue

                current_price_data = get_price(row_dict["ticker"])
                if not current_price_data:
                    continue
                current_price = current_price_data.get("last") or current_price_data.get("close")
                if not current_price:
                    continue

                return_5d = (current_price - price_at_call) / price_at_call
                hit_5d = self._compute_hit(row_dict["signal"], return_5d)

                update_data: dict[str, Any] = {
                    "return_5d": return_5d,
                    "hit_5d": hit_5d,
                    "id": row_dict["id"],
                }

                # Optionally backfill 20d
                if self._config.scorer.backfill_20d and days_elapsed >= 20:
                    update_data["return_20d"] = return_5d  # use current price as approximation
                    update_data["hit_20d"] = hit_5d

                if "return_20d" in update_data:
                    conn.execute(
                        """UPDATE agent_scorecards
                           SET return_5d = :return_5d, hit_5d = :hit_5d,
                               return_20d = :return_20d, hit_20d = :hit_20d
                           WHERE id = :id""",
                        update_data,
                    )
                else:
                    conn.execute(
                        """UPDATE agent_scorecards
                           SET return_5d = :return_5d, hit_5d = :hit_5d
                           WHERE id = :id""",
                        update_data,
                    )
                updated += 1

        if updated:
            logger.info("Back-filled returns for %d scorecards", updated)
        return updated

    @staticmethod
    def _compute_hit(signal: str, realized_return: float) -> int:
        """1 if the agent's directional call matches the realized return."""
        if signal == "BULLISH" and realized_return > 0:
            return 1
        if signal == "BEARISH" and realized_return < 0:
            return 1
        if signal == "NEUTRAL":
            return 1 if abs(realized_return) < 0.02 else 0
        return 0

    # ── Per-agent metrics ─────────────────────────────────────────────

    def get_returns(self, agent_id: str, window_days: int | None = None) -> list[dict]:
        """Fetch scorecard rows with non-null return_5d for a given agent."""
        window = window_days or self._config.scorer.rolling_window_days
        cutoff = (datetime.now() - timedelta(days=window)).strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT return_5d, hit_5d FROM agent_scorecards
                   WHERE agent_id = ? AND date >= ? AND return_5d IS NOT NULL
                   ORDER BY date DESC""",
                (agent_id, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_agent_metrics(self) -> dict[str, dict]:
        """Compute Sharpe + hit_rate for each agent in the rolling window.

        Returns: {agent_id: {"sharpe": float, "hit_rate": float}}
        """
        result: dict[str, dict] = {}
        for agent_id in AGENT_MAP:
            returns = self.get_returns(agent_id)
            if len(returns) < self._config.scorer.min_samples:
                result[agent_id] = {"sharpe": 0.0, "hit_rate": 0.0}
                continue
            returns_5d = [r["return_5d"] for r in returns]
            sharpe = compute_agent_sharpe(returns_5d)
            hit_rate = sum(1 for r in returns if r["hit_5d"]) / len(returns)
            result[agent_id] = {"sharpe": round(sharpe, 4), "hit_rate": round(hit_rate, 4)}
        return result

    # ── Weight management ─────────────────────────────────────────────

    def get_weight(self, agent_id: str) -> float:
        return self._weights.get(agent_id, 1.0)

    def save_weight(self, agent_id: str, weight: float, task_id: str | None = None) -> None:
        self._weights[agent_id] = weight
        from datetime import datetime
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO agent_weights (agent_id, weight, updated_at, updated_by_task_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 weight = excluded.weight,
                 updated_at = excluded.updated_at,
                 updated_by_task_id = excluded.updated_by_task_id""",
            (agent_id, weight, datetime.now().isoformat(), task_id),
        )
        conn.commit()
        conn.close()

    def get_all_weights(self) -> dict[str, float]:
        return dict(self._weights)


def compute_agent_sharpe(
    returns_5d: list[float],
    annualize_factor: float = 252 / 5,
) -> float:
    """Compute annualized Sharpe from 5-day returns.

    Reuses the same formula as metrics.py but with 5d returns
    instead of daily equity changes.
    """
    if len(returns_5d) < 5:
        return 0.0
    arr = np.array(returns_5d)
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((arr.mean() / std) * np.sqrt(annualize_factor))
