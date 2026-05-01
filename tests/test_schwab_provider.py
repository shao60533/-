"""SchwabProvider unit tests — fully mocked, no network."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from stock_trading_system.data.schwab_provider import SchwabProvider


# ── Fixtures ──────────────────────────────────────────────────────────


def _enabled_config(token_path: str) -> dict:
    return {
        "schwab": {
            "enabled": True,
            "app_key": "key",
            "app_secret": "secret",
            "token_path": token_path,
        }
    }


@pytest.fixture
def token_file(tmp_path):
    p = tmp_path / "schwab_token.json"
    p.write_text('{"token": "fake"}')
    return str(p)


def _quote_response(symbol: str, **overrides) -> MagicMock:
    quote = {
        "lastPrice": 150.25, "openPrice": 149.5, "highPrice": 151.0,
        "lowPrice": 149.0, "closePrice": 149.8, "bidPrice": 150.20,
        "askPrice": 150.30, "totalVolume": 50_000_000,
        "quoteTime": 1730000000000,
    }
    quote.update(overrides)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {symbol: {"symbol": symbol, "quote": quote}}
    return resp


# ── enabled property ─────────────────────────────────────────────────


def test_enabled_false_when_flag_off(token_file):
    cfg = _enabled_config(token_file)
    cfg["schwab"]["enabled"] = False
    p = SchwabProvider(cfg)
    assert p.enabled is False


def test_enabled_false_without_token_file(tmp_path):
    cfg = _enabled_config(str(tmp_path / "nope.json"))
    p = SchwabProvider(cfg)
    assert p.enabled is False


def test_enabled_false_without_app_key(token_file):
    cfg = _enabled_config(token_file)
    cfg["schwab"]["app_key"] = ""
    p = SchwabProvider(cfg)
    assert p.enabled is False


def test_enabled_true_when_all_set(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    assert p.enabled is True


# ── token_age_days ───────────────────────────────────────────────────


def test_token_age_days_returns_none_when_missing(tmp_path):
    cfg = _enabled_config(str(tmp_path / "nope.json"))
    p = SchwabProvider(cfg)
    assert p.token_age_days() is None


def test_token_age_days_recent(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    age = p.token_age_days()
    assert age is not None and age < 1


# ── get_stock_price ──────────────────────────────────────────────────


def test_get_stock_price_returns_none_when_disabled(tmp_path):
    cfg = _enabled_config(str(tmp_path / "nope.json"))
    p = SchwabProvider(cfg)
    assert p.get_stock_price("AAPL") is None


def test_get_stock_price_normalizes(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    fake.get_quote.return_value = _quote_response("AAPL")
    with patch.object(p, "_get_client", return_value=fake):
        result = p.get_stock_price("AAPL")
    assert result == {
        "ticker": "AAPL", "last": 150.25, "close": 149.8,
        "open": 149.5, "high": 151.0, "low": 149.0,
        "bid": 150.20, "ask": 150.30,
        "volume": 50_000_000,
        "source": "schwab", "timestamp_ms": 1730000000000,
    }


def test_get_stock_price_handles_http_error(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    err = MagicMock()
    err.status_code = 401
    fake.get_quote.return_value = err
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_price("AAPL") is None


def test_get_stock_price_handles_exception(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    fake.get_quote.side_effect = RuntimeError("network")
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_price("AAPL") is None


def test_get_stock_price_returns_none_if_quote_block_empty(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    err = MagicMock()
    err.status_code = 200
    err.json.return_value = {}
    fake.get_quote.return_value = err
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_price("AAPL") is None


# ── get_stock_price_batch (key performance path) ─────────────────────


def test_batch_returns_empty_when_disabled(tmp_path):
    cfg = _enabled_config(str(tmp_path / "nope.json"))
    p = SchwabProvider(cfg)
    assert p.get_stock_price_batch(["AAPL", "TSLA"]) == {}


def test_batch_returns_empty_for_empty_list(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    assert p.get_stock_price_batch([]) == {}


def test_batch_normalizes_each_symbol(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "AAPL": {"symbol": "AAPL", "quote": {
            "lastPrice": 150.0, "closePrice": 149.0, "totalVolume": 100,
            "quoteTime": 1730000000000,
        }},
        "TSLA": {"symbol": "TSLA", "quote": {
            "lastPrice": 250.0, "closePrice": 248.0, "totalVolume": 200,
            "quoteTime": 1730000000000,
        }},
    }
    fake.get_quotes.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        out = p.get_stock_price_batch(["AAPL", "TSLA"])
    assert set(out.keys()) == {"AAPL", "TSLA"}
    assert out["AAPL"]["last"] == 150.0
    assert out["TSLA"]["last"] == 250.0
    fake.get_quotes.assert_called_once()
    args, _ = fake.get_quotes.call_args
    assert args[0] == ["AAPL", "TSLA"]


def test_batch_uppercases_and_strips(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "AAPL": {"quote": {"lastPrice": 1, "closePrice": 1, "quoteTime": 0}},
    }
    fake.get_quotes.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        out = p.get_stock_price_batch(["  aapl  ", "", "  "])
    assert "AAPL" in out
    args, _ = fake.get_quotes.call_args
    assert args[0] == ["AAPL"]


def test_batch_caps_at_500_symbols(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    fake.get_quotes.return_value = resp
    tickers = [f"T{i}" for i in range(600)]
    with patch.object(p, "_get_client", return_value=fake):
        p.get_stock_price_batch(tickers)
    args, _ = fake.get_quotes.call_args
    assert len(args[0]) == 500


def test_batch_swallows_http_error(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 429
    fake.get_quotes.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_price_batch(["AAPL"]) == {}


def test_batch_skips_unusable_quote_rows(token_file):
    """Symbols whose quote payload has neither last nor close are dropped."""
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "AAPL": {"quote": {"lastPrice": 150, "closePrice": 149,
                            "quoteTime": 0}},
        "BAD": {"quote": {"quoteTime": 0}},  # no price → drop
    }
    fake.get_quotes.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        out = p.get_stock_price_batch(["AAPL", "BAD"])
    assert set(out.keys()) == {"AAPL"}


# ── get_stock_history ────────────────────────────────────────────────


def test_history_disabled_returns_none(tmp_path):
    cfg = _enabled_config(str(tmp_path / "nope.json"))
    p = SchwabProvider(cfg)
    assert p.get_stock_history("AAPL") is None


def test_history_daily_normalizes(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candles": [
            {"datetime": 1730000000000, "open": 100, "high": 105,
             "low": 99, "close": 104, "volume": 1000},
            {"datetime": 1730086400000, "open": 104, "high": 106,
             "low": 103, "close": 105, "volume": 1100},
        ]
    }
    fake.get_price_history_every_day.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        df = p.get_stock_history("AAPL", period="1mo", interval="1d")
    assert df is not None
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == 104


def test_history_returns_none_when_no_candles(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candles": []}
    fake.get_price_history_every_day.return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_history("AAPL") is None


def test_history_routes_intraday_intervals(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candles": [
        {"datetime": 1730000000000, "open": 1, "high": 2, "low": 0,
         "close": 1.5, "volume": 10},
    ]}
    for method, interval in [
        ("get_price_history_every_minute", "1m"),
        ("get_price_history_every_five_minutes", "5m"),
        ("get_price_history_every_fifteen_minutes", "15m"),
        ("get_price_history_every_thirty_minutes", "30m"),
        ("get_price_history_every_week", "1wk"),
    ]:
        getattr(fake, method).return_value = resp
    with patch.object(p, "_get_client", return_value=fake):
        for interval in ["1m", "5m", "15m", "30m", "1wk"]:
            df = p.get_stock_history("AAPL", interval=interval)
            assert df is not None and len(df) == 1
    fake.get_price_history_every_minute.assert_called_once()
    fake.get_price_history_every_five_minutes.assert_called_once()
    fake.get_price_history_every_fifteen_minutes.assert_called_once()
    fake.get_price_history_every_thirty_minutes.assert_called_once()
    fake.get_price_history_every_week.assert_called_once()


def test_history_swallows_exception(token_file):
    p = SchwabProvider(_enabled_config(token_file))
    fake = MagicMock()
    fake.get_price_history_every_day.side_effect = RuntimeError("boom")
    with patch.object(p, "_get_client", return_value=fake):
        assert p.get_stock_history("AAPL") is None
