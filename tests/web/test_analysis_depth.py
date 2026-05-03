"""depth (standard / deep) end-to-end persistence + DTO contract.

analysis-depth-mode v1.0 把 quick/standard/deep 三档收敛为 standard/deep
二档。本测试模块覆盖 ``_normalize_depth`` 的旧 API 收敛行为：

- 内部 canonical 集合仅 ``{"standard", "deep"}``
- 旧值 ``quick`` / ``NULL`` / ``""`` / 任何无法识别的值 → ``standard``
- ``deep`` 显式输入 → ``deep``

新字段 ``deep_analysis`` (bool) 与 ``normalize_analysis_depth`` 入口契约
在 ``test_analysis_depth_mode.py`` 单独覆盖。
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.portfolio.database import (
    PortfolioDatabase,
    _normalize_depth,
)


@pytest.mark.parametrize("incoming,expected", [
    (None,         "standard"),
    ("",           "standard"),
    ("Quick",      "standard"),  # v1.0: 旧 quick 兼容映射为 standard
    ("standard",   "standard"),
    ("DEEP",       "deep"),
    ("invalid",    "standard"),
    (42,           "standard"),
])
def test_normalize_depth_canonical_set(incoming, expected):
    assert _normalize_depth(incoming) == expected


def test_save_analysis_persists_depth(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "deep",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "deep"


def test_save_analysis_defaults_depth_when_missing(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard"


def test_save_analysis_invalid_depth_falls_back_to_standard(tmp_path):
    db = PortfolioDatabase(str(tmp_path / "p.db"))
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "ultra-deep",
    })
    row = db.get_analysis_by_id(aid)
    assert row["depth"] == "standard"


def test_history_list_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    # v1.0: 即使外部传入 quick，DTO 也归一化为 standard 返回 — quick 不再
    # 作为产品状态（用 deep 写入更直观，DTO 应原样返）。
    db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get("/api/history?limit=5").get_json()
    assert body["items"], "list must return at least one item"
    assert body["items"][0]["depth"] == "deep"


def test_history_detail_dto_returns_depth(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "deep"


def test_history_detail_legacy_null_depth_renders_as_standard(
    alice_client, app_client,
):
    """Pre-v1.16 rows have NULL depth — DTO normalises to 'standard'
    so the UI never has to special-case it."""
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id,
    })
    with sqlite3.connect(app_client["db_path"]) as conn:
        conn.execute(
            "UPDATE analysis_history SET depth = NULL WHERE id = ?", (aid,),
        )
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "standard"


def test_task_store_persists_depth(tmp_path):
    """Workers route results through TaskStore, which is the canonical
    write path. It must persist ``depth`` and normalise unknowns."""
    from stock_trading_system.tasks.task_store import TaskStore
    store = TaskStore(str(tmp_path / "tasks.db"))
    ref = store.save_result("analysis", "task-1", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "deep",
    })
    rid = int(ref.split(":", 1)[1])
    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (rid,),
        ).fetchone()
    assert row["depth"] == "deep"


def test_analyzer_iteration_toggle_standard_vs_deep(tmp_path):
    """v1.0: standard 永远关 iteration（不读 config）；deep 强制开
    iteration，仅当 ``config.iteration.enabled=false`` 时降级为 standard。"""
    from stock_trading_system.agents.analyzer import StockAnalyzer

    # 1) standard + config.iteration.enabled=True → 仍然 False
    #    （v1.0 关键变化：standard 不再跟随 config）
    a1 = StockAnalyzer({"iteration": {"enabled": True}})
    a1._depth_override = "standard"
    assert a1._iteration_enabled is False

    # 2) deep + config.iteration.enabled=True → True
    a2 = StockAnalyzer({"iteration": {"enabled": True}})
    a2._depth_override = "deep"
    assert a2._iteration_enabled is True

    # 3) deep + config.iteration.enabled=False → 降级为 False，且原因被记录
    a3 = StockAnalyzer({"iteration": {"enabled": False}})
    a3._depth_override = "deep"
    assert a3._iteration_enabled is False
    assert a3._iteration_downgrade_reason == "system_iteration_disabled"

    # 4) 旧 quick 兼容：等价于 standard，永远 False
    a4 = StockAnalyzer({"iteration": {"enabled": True}})
    a4._depth_override = "quick"
    assert a4._iteration_enabled is False
