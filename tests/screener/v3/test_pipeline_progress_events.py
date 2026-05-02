"""Pipeline progress events for screener-history v1.1.

The frontend ``ScreenerV3Progress`` component consumes these events to
advance the V3-shaped stage timeline (parse / universe / bundle / guru
/ roundtable / aggregate). Without them, the running view falls back to
zero progress and users can't tell which phase is active.

Tests here pin the event contract — what type of events are emitted,
their stage labels, and the per-ticker round-table progress shape.
Direct calls into ``_emit_stage`` and ``_run_roundtable`` keep the
tests fast and avoid mocking the full guru pool.
"""

from __future__ import annotations

import asyncio

import pytest

from stock_trading_system.screener.v3.guru_agents.base import GuruSignal
from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def progress_log():
    """Container the pipeline writes events into via ``on_progress``."""
    return []


@pytest.fixture
def pipeline(progress_log):
    """Pipeline wired to capture every progress event."""
    return ScreenerV3Pipeline(
        config={},
        local_cache=None,
        on_progress=lambda evt: progress_log.append(evt),
    )


class TestEmitStage:
    def test_start_emits_screen_v3_stage_start(self, pipeline, progress_log):
        pipeline._emit_stage("parse", "start")
        assert len(progress_log) == 1
        evt = progress_log[0]
        assert evt["type"] == "screen_v3_stage_start"
        assert evt["stage"] == "parse"

    def test_done_emits_screen_v3_stage_done_with_extras(self, pipeline, progress_log):
        pipeline._emit_stage("guru", "done", total=80, signals=80)
        assert len(progress_log) == 1
        evt = progress_log[0]
        assert evt["type"] == "screen_v3_stage_done"
        assert evt["stage"] == "guru"
        assert evt["total"] == 80
        assert evt["signals"] == 80

    def test_no_progress_sink_is_silent(self):
        """Pipeline without on_progress must not raise."""
        silent = ScreenerV3Pipeline(config={}, on_progress=None)
        # Both phases — neither should raise.
        silent._emit_stage("parse", "start")
        silent._emit_stage("parse", "done", count=10)

    def test_broken_progress_sink_does_not_kill_pipeline(self):
        """A buggy frontend listener must NOT crash the run."""
        def boom(_evt):
            raise RuntimeError("listener exploded")

        broken = ScreenerV3Pipeline(config={}, on_progress=boom)
        # Must swallow the exception silently.
        broken._emit_stage("parse", "start")


class TestRoundtableProgressEvents:
    """``_run_roundtable`` MUST emit one roundtable_start + one
    roundtable_done per ticker so the frontend stage cell can show
    Top-N debate progress (e.g. ``2/5 · AAPL``)."""

    @staticmethod
    def _signal(guru: str, ticker: str, signal: str, confidence: float = 0.8) -> GuruSignal:
        return GuruSignal(
            guru=guru, ticker=ticker, signal=signal,
            confidence=confidence, reasoning="test reasoning",
            sub_analyses=[], total_score=80,
        )

    def test_roundtable_emits_start_once_and_done_per_ticker(
        self, pipeline, progress_log,
    ):
        signals = [
            self._signal("buffett", "AAPL", "bullish"),
            self._signal("graham",  "AAPL", "bearish"),
            self._signal("lynch",   "MSFT", "bullish"),
            self._signal("munger",  "MSFT", "bullish"),
        ]
        top_tickers = ["AAPL", "MSFT"]
        # v1.4: ``_run_roundtable`` now returns ``(results, status)``
        # so the caller can surface ``roundtable_status`` in run_metadata.
        # Status is "fallback" when the judge LLM can't be constructed —
        # which is the case in this test (no provider config set up).
        results, status = _run(
            pipeline._run_roundtable(signals, top_tickers, context={}),
        )

        assert set(results.keys()) == {"AAPL", "MSFT"}
        assert status in ("success", "fallback")

        starts = [e for e in progress_log if e.get("type") == "roundtable_start"]
        dones  = [e for e in progress_log if e.get("type") == "roundtable_done"]
        assert len(starts) == 1, "exactly one roundtable_start must fire"
        assert starts[0]["tickers"] == top_tickers
        assert len(dones) >= 1, (
            f"expected at least one roundtable_done, got {len(dones)}"
        )
        # Each emitted done event carries the ticker + consensus/dissent
        # so the front-end matrix can render unanimous/contested colors.
        for evt in dones:
            assert evt["ticker"] in top_tickers
            assert "consensus" in evt
            assert "dissent" in evt

    def test_roundtable_with_no_progress_sink_still_returns_results(self):
        """Behaviour without a listener is unchanged — events suppressed,
        results returned. Guards us against a regression where the new
        event code path silently drops the dict."""
        silent = ScreenerV3Pipeline(config={}, on_progress=None)
        sigs = [self._signal("buffett", "AAPL", "bullish")]
        results, _status = _run(
            silent._run_roundtable(sigs, ["AAPL"], context={}),
        )
        assert "AAPL" in results
