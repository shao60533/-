"""Ticker normalization + validation tests.

Covers PRD paper-trade-list v1.0 P0-1:
  - typo / non-existent ticker rejected (no DB write)
  - valid US → canonical uppercase
  - CN suffix → 6-digit canonical
  - empty / None rejected
  - allow_quote_failure → form check still rejects garbage
  - process_analysis with invalid ticker returns skipped (no session row)
"""

from __future__ import annotations

import pytest

from stock_trading_system.utils.ticker_validator import (
    InvalidTickerError,
    TickerValidation,
    _reset_cache_for_tests,
    normalize_and_validate_ticker,
)


@pytest.fixture(autouse=True)
def _wipe_cache():
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


def _fake_quote(price: float | None):
    def _f(_t: str):
        if price is None:
            return None
        return {"last": price, "date": "2026-05-16"}

    return _f


class TestNormalizeAndValidateTicker:
    def test_us_valid_with_quote(self):
        v = normalize_and_validate_ticker("goog", quote_fn=_fake_quote(123.4))
        assert v == TickerValidation(
            canonical="GOOG",
            market="us",
            has_quote=True,
            quote_price=123.4,
            quote_date="2026-05-16",
        )

    def test_strips_whitespace_and_uppercases(self):
        v = normalize_and_validate_ticker("  aapl  ", quote_fn=_fake_quote(200.0))
        assert v.canonical == "AAPL"

    def test_cn_with_sh_suffix_canonical_is_6_digits(self):
        v = normalize_and_validate_ticker("600519.SH", quote_fn=_fake_quote(1800.0))
        assert v.canonical == "600519"
        assert v.market == "cn"

    def test_cn_without_suffix_also_valid(self):
        v = normalize_and_validate_ticker("000001", quote_fn=_fake_quote(10.0))
        assert v.canonical == "000001"
        assert v.market == "cn"

    def test_typo_too_many_letters_rejected(self):
        with pytest.raises(InvalidTickerError) as ei:
            normalize_and_validate_ticker("GOOGLELONG", quote_fn=_fake_quote(123.4))
        assert "形态校验失败" in ei.value.reason

    def test_typo_mixed_garbage_rejected(self):
        with pytest.raises(InvalidTickerError):
            normalize_and_validate_ticker("1U7BLAH", quote_fn=_fake_quote(123.4))

    def test_empty_rejected(self):
        with pytest.raises(InvalidTickerError):
            normalize_and_validate_ticker("   ", quote_fn=_fake_quote(123.4))

    def test_none_rejected(self):
        with pytest.raises(InvalidTickerError):
            normalize_and_validate_ticker(None, quote_fn=_fake_quote(123.4))  # type: ignore[arg-type]

    def test_quote_miss_rejected_by_default(self):
        # Form OK but data source has no quote → reject (catches SXOL-style)
        with pytest.raises(InvalidTickerError) as ei:
            normalize_and_validate_ticker("SXOL", quote_fn=_fake_quote(None))
        assert "市场未找到" in ei.value.reason

    def test_quote_miss_allowed_with_flag(self):
        v = normalize_and_validate_ticker(
            "SXOL", quote_fn=_fake_quote(None), allow_quote_failure=True,
        )
        assert v.canonical == "SXOL"
        assert v.has_quote is False
        assert v.quote_price is None

    def test_quote_miss_form_still_rejects_with_flag(self):
        # Even with allow_quote_failure, form check still rejects garbage
        with pytest.raises(InvalidTickerError):
            normalize_and_validate_ticker(
                "TOTALLY_INVALID",
                quote_fn=_fake_quote(None),
                allow_quote_failure=True,
            )

    def test_cache_short_circuits_second_call(self):
        calls: list[str] = []

        def counting_fn(t: str):
            calls.append(t)
            return {"last": 100.0, "date": "2026-05-16"}

        normalize_and_validate_ticker("AAPL", quote_fn=counting_fn)
        normalize_and_validate_ticker("AAPL", quote_fn=counting_fn)
        assert len(calls) == 1


class TestProcessAnalysisGuard:
    """Smoke test that the event_executor guard skips invalid tickers."""

    def test_invalid_ticker_skipped_no_session_created(self, tmp_path):
        from stock_trading_system.strategy.paper_trader import event_executor as ee
        from stock_trading_system.strategy.paper_trader.session_store import (
            PaperTradeStore,
        )

        db_file = tmp_path / "paper.db"
        store = PaperTradeStore(str(db_file))

        result = ee.process_analysis(
            store,
            analysis_id=1,
            ticker="ZZZZZZZ",  # 7 letters — form invalid
            analysis_date="2026-05-16",
            signal="BUY",
            advice=None,
            user_id=42,
        )
        assert result["ok"] is False
        assert "invalid_ticker" in (result.get("reason") or "")

        # No session row should have been created with that ticker
        sessions = store.list_sessions()
        assert all(s.get("ticker") != "ZZZZZZZ" for s in sessions)
