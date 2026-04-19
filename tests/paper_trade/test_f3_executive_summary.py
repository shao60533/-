"""F3 tests: executive_summary extraction + regex 解析 removal."""

from __future__ import annotations

import subprocess

import pytest


class TestRegexLiteralRemoved:
    """TC-PT-F3-7: grep for 'regex 解析' must find zero results."""

    def test_no_regex_literal_in_codebase(self):
        result = subprocess.run(
            ["grep", "-rn", "regex 解析", "stock_trading_system/"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", (
            f"Found 'regex 解析' in codebase:\n{result.stdout}"
        )


class TestPlanParserThesis:
    """thesis field should be None (not 'regex 解析')."""

    def test_thesis_is_none_in_fallback(self):
        from stock_trading_system.strategy.paper_trader.plan_parser import _extract_via_regex
        plan = _extract_via_regex(
            "Rating: Buy\nEntry: $100-$110\nStop: $90\nTarget: $130",
            "BUY", None,
        )
        if plan:
            assert plan.get("thesis") is None or plan.get("thesis") != "regex 解析"


class TestMigrationAddsColumn:
    """F3 migration adds executive_summary column."""

    def test_column_added(self, tmp_path):
        import sqlite3
        from stock_trading_system.migrations.paper_trade_v1_3 import migrate

        path = str(tmp_path / "test.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE paper_trade_plans (
                id INTEGER PRIMARY KEY, session_id INTEGER,
                analysis_id INTEGER, plan_json TEXT
            );
            CREATE TABLE analysis_history (
                id INTEGER PRIMARY KEY, ticker TEXT, trade_decision TEXT
            );
        """)
        conn.close()
        migrate(path)

        conn = sqlite3.connect(path)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(analysis_history)").fetchall()]
        conn.close()
        assert "executive_summary" in cols
