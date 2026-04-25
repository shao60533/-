"""Investment master / guru philosophy engines."""

from stock_trading_system.screener.v2.gurus.base import BaseGuru, GuruMatch
from stock_trading_system.screener.v2.gurus.buffett import BuffettGuru
from stock_trading_system.screener.v2.gurus.graham import GrahamGuru
from stock_trading_system.screener.v2.gurus.lynch import LynchGuru
from stock_trading_system.screener.v2.gurus.oneil import ONeilGuru


# Placeholder metadata for future gurus (not yet implemented in Phase 1).
_PLACEHOLDER_META = [
    {"name": "munger", "display_name": "Charlie Munger", "philosophy": "质量优先 / 多元模型",
     "principles": ["优秀生意 > 便宜价", "管理层诚信", "心智模型筛选", "避免复杂"],
     "motto": "反过来想，总是反过来想", "avatar_initials": "CM", "avatar_color": "#ff8c00"},
    {"name": "marks", "display_name": "Howard Marks", "philosophy": "周期思维 / 逆向",
     "principles": ["周期位置", "第二层思维", "风险调整收益", "逆向机会"],
     "motto": "你不能预测，但你能准备", "avatar_initials": "HM", "avatar_color": "#a855f7"},
    {"name": "soros", "display_name": "George Soros", "philosophy": "反身性 / 宏观",
     "principles": ["反身性循环", "宏观趋势", "情绪极端", "大额高概率"],
     "motto": "重要的不是你对错，而是对时赚多少、错时亏多少",
     "avatar_initials": "GS", "avatar_color": "#ff3860"},
    {"name": "simons", "display_name": "Jim Simons", "philosophy": "量化 / 统计套利",
     "principles": ["统计异常", "均值回归", "低相关因子", "高频信号"],
     "motto": "相信数据，不相信叙事", "avatar_initials": "JS", "avatar_color": "#00d4ff"},
]


def build_gurus(config: dict, enabled: list[str] | None = None) -> dict:
    """Build enabled gurus only. `enabled` is a list of guru names."""
    available = {
        "buffett": BuffettGuru(config),
        "graham": GrahamGuru(config),
        "lynch": LynchGuru(config),
        "oneil": ONeilGuru(config),
    }
    if enabled is None:
        return available
    return {k: v for k, v in available.items() if k in enabled}


def all_guru_metadata() -> list[dict]:
    """Return UI metadata for all 8 gurus (4 implemented + 4 placeholders)."""
    implemented = [
        BuffettGuru({}).metadata(),
        GrahamGuru({}).metadata(),
        LynchGuru({}).metadata(),
        ONeilGuru({}).metadata(),
    ]
    for m in implemented:
        m["implemented"] = True
    for m in _PLACEHOLDER_META:
        m["implemented"] = False
    return implemented + _PLACEHOLDER_META


__all__ = [
    "BaseGuru", "GuruMatch",
    "BuffettGuru", "GrahamGuru", "LynchGuru", "ONeilGuru",
    "build_gurus", "all_guru_metadata",
]
