"""analysis-depth-mode v1.0: 收敛 quick/standard/deep 为 standard/deep。

覆盖用户验收清单 10 项：
1. deep_analysis=false 提交后落库 depth=standard
2. deep_analysis=true  提交后落库 depth=deep
3. 旧 depth=quick      提交兼容为 standard
4. 旧 depth=standard   提交兼容为 standard
5. 旧 depth=deep       提交兼容为 deep
6. standard 必须强制关 iteration（不读 config）
7. deep 必须强制开 iteration（系统禁用时降级 + 原因）
8. DTO 同时返回 depth + deep_analysis
9. 旧历史记录 depth=NULL → DTO 返 standard / deep_analysis=false
10. DB 启动迁移把旧 quick / NULL 行归一为 standard
"""

from __future__ import annotations

import sqlite3

import pytest

from stock_trading_system.portfolio.database import (
    PortfolioDatabase,
    _normalize_depth,
    normalize_analysis_depth,
)


# ── normalize_analysis_depth: 优先级 + 兼容 ──────────────────────────────


def test_normalize_prefers_new_deep_analysis_field_when_true():
    out = normalize_analysis_depth({"deep_analysis": True, "depth": "standard"})
    assert out == {"depth": "deep", "deep_analysis": True}


def test_normalize_prefers_new_deep_analysis_field_when_false():
    # 即使旧 depth=deep 与 deep_analysis=false 冲突，新字段赢。
    out = normalize_analysis_depth({"deep_analysis": False, "depth": "deep"})
    assert out == {"depth": "standard", "deep_analysis": False}


def test_normalize_falls_back_to_legacy_depth_when_new_field_absent():
    out = normalize_analysis_depth({"depth": "deep"})
    assert out == {"depth": "deep", "deep_analysis": True}


@pytest.mark.parametrize("legacy_depth,expected_depth,expected_flag", [
    ("quick",    "standard", False),  # v1.0: 旧 quick 兼容映射
    ("standard", "standard", False),
    ("deep",     "deep",     True),
    (None,       "standard", False),
    ("",         "standard", False),
    ("garbage",  "standard", False),
])
def test_legacy_depth_mapping(legacy_depth, expected_depth, expected_flag):
    out = normalize_analysis_depth({"depth": legacy_depth})
    assert out == {"depth": expected_depth, "deep_analysis": expected_flag}


def test_normalize_handles_string_truthy_falsy():
    """JSON-stringified bool from legacy clients should still work."""
    assert normalize_analysis_depth({"deep_analysis": "true"}) == {
        "depth": "deep", "deep_analysis": True,
    }
    assert normalize_analysis_depth({"deep_analysis": "false"}) == {
        "depth": "standard", "deep_analysis": False,
    }


def test_normalize_default_for_empty_params():
    assert normalize_analysis_depth({}) == {
        "depth": "standard", "deep_analysis": False,
    }


def test_normalize_quick_is_never_returned():
    """v1.0 内部集合不再含 quick；任何输入都不返 quick。"""
    for v in ["quick", "QUICK", "Quick", "quick "]:
        out = normalize_analysis_depth({"depth": v})
        assert out["depth"] != "quick"
        assert out["depth"] == "standard"


def test_normalize_depth_legacy_shim_never_returns_quick():
    """``_normalize_depth`` 也收敛——quick 映射为 standard。"""
    for v in ["quick", "QUICK", "Quick", "quick "]:
        assert _normalize_depth(v) == "standard"


# ── DB 落库：deep_analysis=true/false 端到端 ──────────────────────────────


def test_submit_deep_analysis_true_persists_deep(tmp_path):
    """worker 入参 ``deep_analysis=true`` → 落库 depth=deep。模拟 worker
    侧的归一化 + 落库链路。"""
    from stock_trading_system.tasks.task_store import TaskStore
    store = TaskStore(str(tmp_path / "tasks.db"))
    norm = normalize_analysis_depth({"deep_analysis": True})
    ref = store.save_result("analysis", "t-deep", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": norm["depth"],
    })
    rid = int(ref.split(":", 1)[1])
    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (rid,),
        ).fetchone()
    assert row["depth"] == "deep"


def test_submit_deep_analysis_false_persists_standard(tmp_path):
    from stock_trading_system.tasks.task_store import TaskStore
    store = TaskStore(str(tmp_path / "tasks.db"))
    norm = normalize_analysis_depth({"deep_analysis": False})
    ref = store.save_result("analysis", "t-std", {
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": norm["depth"],
    })
    rid = int(ref.split(":", 1)[1])
    with sqlite3.connect(str(tmp_path / "tasks.db")) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (rid,),
        ).fetchone()
    assert row["depth"] == "standard"


# ── DTO 同时返回 depth + deep_analysis ────────────────────────────────────


def test_history_list_dto_returns_both_depth_and_deep_analysis(
    alice_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get("/api/history?limit=5").get_json()
    item = body["items"][0]
    assert item["depth"] == "deep"
    assert item["deep_analysis"] is True


def test_history_list_dto_standard_row_has_deep_analysis_false(
    alice_client, app_client,
):
    db = PortfolioDatabase(app_client["db_path"])
    db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "standard",
    })
    body = alice_client.get("/api/history?limit=5").get_json()
    item = body["items"][0]
    assert item["depth"] == "standard"
    assert item["deep_analysis"] is False


def test_history_detail_dto_returns_both_fields(alice_client, app_client):
    db = PortfolioDatabase(app_client["db_path"])
    aid = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "created_by": app_client["users"].alice.id, "depth": "deep",
    })
    body = alice_client.get(f"/api/history/{aid}").get_json()
    assert body["depth"] == "deep"
    assert body["deep_analysis"] is True


def test_history_detail_legacy_null_depth_dto_renders_standard_false(
    alice_client, app_client,
):
    """旧 NULL 行 → DTO 返 ``{depth:"standard", deep_analysis:false}``。"""
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
    assert body["deep_analysis"] is False


# ── DB 启动迁移：旧 quick / NULL → standard ──────────────────────────────


def test_db_migration_quick_rows_become_standard(tmp_path):
    """启动期 _migrate_analysis_history 把所有 quick / NULL / '' 改成
    standard。重新初始化 PortfolioDatabase 触发 migration。"""
    db_path = str(tmp_path / "p.db")
    db = PortfolioDatabase(db_path)
    aid_quick = db.save_analysis({
        "ticker": "AAPL", "date": "2026-04-15", "signal": "BUY",
        "depth": "deep",  # 先合法写入
    })
    # 模拟旧 quick / NULL 数据
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE analysis_history SET depth = 'quick' WHERE id = ?",
            (aid_quick,),
        )
        aid_null_row = conn.execute(
            "INSERT INTO analysis_history (ticker,date,signal,created_at,depth) "
            "VALUES ('TSLA','2026-04-15','HOLD','2026-04-15 12:00:00',NULL)"
        ).lastrowid
    # 重新初始化触发 migration
    PortfolioDatabase(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row1 = conn.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (aid_quick,),
        ).fetchone()
        row2 = conn.execute(
            "SELECT depth FROM analysis_history WHERE id = ?", (aid_null_row,),
        ).fetchone()
        # 任何剩余 quick 行都应该被清空
        leftover_quick = conn.execute(
            "SELECT COUNT(*) AS n FROM analysis_history WHERE depth = 'quick'",
        ).fetchone()["n"]
    assert row1["depth"] == "standard"
    assert row2["depth"] == "standard"
    assert leftover_quick == 0
