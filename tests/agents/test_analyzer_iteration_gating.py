"""analysis-depth-mode v1.0: ``StockAnalyzer._iteration_enabled`` 收敛。

新规则（与 v1.16 不同）：
- ``standard`` **永远** 关闭 iteration —— 不再读 ``config.iteration.enabled``。
  原因：v1.16 让 standard 跟随 config，导致 ops 改 config 后用户感知不到
  的产品语义切换（"标准分析" 静默变成迭代分析）。v1.0 把"是否开启深度
  分析"做成纯产品级二元决定。
- ``deep`` 默认开启 iteration；当 ``config.iteration.enabled = false`` 时
  **明确降级**为 standard 行为，并在 ``self._iteration_downgrade_reason``
  上记录 ``"system_iteration_disabled"``，worker 把它写到 task result 让
  下游 UX 可显示降级 banner。**不允许静默装作 iteration 已开**。
- 兼容：``_depth_override = "quick"`` 视为 ``standard``。
"""

from __future__ import annotations

from stock_trading_system.agents.analyzer import StockAnalyzer


def test_standard_forces_iteration_off_even_when_config_enabled():
    """v1.0 关键变化：standard 不读 config.iteration.enabled。"""
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    analyzer._depth_override = "standard"
    assert analyzer._iteration_enabled is False
    # 也不应有降级原因 —— 这是用户明确选择的标准模式，不是降级。
    assert analyzer._iteration_downgrade_reason is None


def test_standard_iteration_off_when_config_disabled():
    analyzer = StockAnalyzer({"iteration": {"enabled": False}})
    analyzer._depth_override = "standard"
    assert analyzer._iteration_enabled is False


def test_deep_forces_iteration_on_when_config_enabled():
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    analyzer._depth_override = "deep"
    assert analyzer._iteration_enabled is True
    assert analyzer._iteration_downgrade_reason is None


def test_deep_downgrades_to_standard_when_config_disabled():
    """系统层禁用 iteration 但用户选 deep —— 明确降级，不静默。"""
    analyzer = StockAnalyzer({"iteration": {"enabled": False}})
    analyzer._depth_override = "deep"
    # 第一次读触发降级
    assert analyzer._iteration_enabled is False
    # 降级原因被记录
    assert analyzer._iteration_downgrade_reason == "system_iteration_disabled"


def test_deep_downgrade_when_config_iteration_section_missing():
    """缺整段 iteration config 等同于 enabled=False，应触发降级。"""
    analyzer = StockAnalyzer({})
    analyzer._depth_override = "deep"
    assert analyzer._iteration_enabled is False
    assert analyzer._iteration_downgrade_reason == "system_iteration_disabled"


def test_legacy_quick_treated_as_standard():
    """旧 quick depth 兼容映射为 standard，永远不开 iteration。"""
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    analyzer._depth_override = "quick"
    assert analyzer._iteration_enabled is False
    assert analyzer._iteration_downgrade_reason is None


def test_iteration_downgrade_reason_clears_on_subsequent_standard_call():
    """同一个 analyzer 实例先用 deep 触发降级、再切 standard 时，原因
    应被清空（避免脏 state）。"""
    analyzer = StockAnalyzer({"iteration": {"enabled": False}})
    # 先 deep → 降级
    analyzer._depth_override = "deep"
    assert analyzer._iteration_enabled is False
    assert analyzer._iteration_downgrade_reason == "system_iteration_disabled"
    # 再切回 standard → 原因清空
    analyzer._depth_override = "standard"
    assert analyzer._iteration_enabled is False
    assert analyzer._iteration_downgrade_reason is None


def test_default_depth_override_none_is_standard_behavior():
    """``_depth_override = None`` 应默认按 standard 处理（不开 iteration）。"""
    analyzer = StockAnalyzer({"iteration": {"enabled": True}})
    analyzer._depth_override = None
    assert analyzer._iteration_enabled is False
