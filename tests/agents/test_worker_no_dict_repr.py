"""Worker output regression test — investment_debate / risk_assessment /
trade_decision columns must never contain a Python dict repr (the
``"{'judge_decision': '...'}"`` pattern that bled through before the
state_normalizer wiring).

This is the production smoke we wish we'd had on 2026-04-29: anyone
adding a new dict-shaped field that escapes normalization will trip this
test before shipping."""

from __future__ import annotations

import re
import types

import pytest

from stock_trading_system.tasks.workers import make_analysis_worker


# Detects the *framing* signature of a Python dict repr — i.e. the value
# stored in the column starts with ``{'key':``. Internal data (e.g. the
# trader echoes a JSON-looking blob from an analyst report) is allowed.
DICT_REPR_FRAMING = re.compile(r"^\s*\{['\"][\w_]+['\"]\s*:")


class _FakeAnalyzer:
    """Mimics StockAnalyzer.analyze() returning AnalysisResult-shaped
    object with dict states (the shape TradingAgents actually produces)."""

    def analyze(self, ticker, date, **_kwargs):
        return types.SimpleNamespace(
            ticker=ticker,
            signal="BUY",
            market_report="Market markdown 文本",
            sentiment_report="Sentiment 文本",
            news_report="News 文本",
            fundamentals_report="Fundamentals 文本",
            investment_debate={
                "judge_decision": "建议增持。",
                "history": "Bull: ... Bear: ...",
                "bull_history": "看多陈述。",
                "bear_history": "看空陈述。",
                "current_response": "Bull final.",
                "count": 4,
            },
            risk_assessment={
                "judge_decision": "整体风险中性。",
                "aggressive_history": "激进派陈述。",
                "conservative_history": "保守派陈述。",
                "neutral_history": "中立派陈述。",
                "history": "略",
                "count": 6,
                "latest_speaker": "Aggressive",
            },
            trade_decision="FINAL TRANSACTION PROPOSAL: **BUY**\n\n推荐买入，理由略。",
            steps=[],
            rendering={},
        )


class _FakeStrategyEngine:
    pass


class _FakePortfolio:
    pass


class _FakeRouter:
    pass


@pytest.fixture
def worker():
    return make_analysis_worker(
        get_analyzer=lambda: _FakeAnalyzer(),
        get_strategy_engine=lambda: _FakeStrategyEngine(),
        get_portfolio=lambda: _FakePortfolio(),
        get_router=lambda: _FakeRouter(),
    )


def test_worker_storage_has_no_dict_repr_framing(worker, monkeypatch):
    """The columns persisted to analysis_history must NOT begin with a
    Python dict repr."""
    # advice helper internally hits portfolio/strategy — short-circuit so
    # the test stays focused on report serialisation.
    from stock_trading_system.tasks import workers as _w

    monkeypatch.setattr(
        _w, "_build_advice_with_snapshot",
        lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        _w, "_resolve_active_provider_model",
        lambda *a, **k: ("qwen", "qwen-plus"),
    )

    out = worker(
        {"ticker": "MSFT", "date": "2026-05-01", "depth": "standard"},
        progress_cb=lambda *a, **k: None,
    )

    for key in ("investment_debate", "risk_assessment", "trade_decision"):
        val = out[key]
        assert isinstance(val, str), f"{key} must be a string, got {type(val)}"
        assert not DICT_REPR_FRAMING.match(val), (
            f"{key} value starts like a Python dict repr: {val[:80]!r}"
        )

    # Markdown headings present where dicts were normalised.
    assert "## 裁判判定" in out["investment_debate"]
    assert "## 风控总判定" in out["risk_assessment"]
    # String trade_decision is preserved verbatim.
    assert "FINAL TRANSACTION PROPOSAL" in out["trade_decision"]
