"""Per-ticker session lifecycle.

Lazily creates one paper_trade_session per ticker on first analysis,
subsequent analyses reuse the same session.
"""

from __future__ import annotations

from stock_trading_system.utils import get_logger

logger = get_logger("paper_trader.ticker_mgr")


def ensure_ticker_session(store, ticker: str, start_date: str,
                          start_capital: float = 100000.0,
                          config: dict | None = None,
                          user_id: int | None = None) -> dict:
    """Return the ticker's session, creating if missing.

    ``user_id`` scopes the lookup/creation so two users tracking the same
    ticker get isolated sessions. ``None`` keeps legacy multi-user-shared
    behaviour for backfill and display callers that don't carry user
    context.

    Validates ``ticker`` through ``normalize_and_validate_ticker`` before
    any DB write so typos / non-existent codes can never reach
    ``paper_trade_sessions``. Quote-failure mode is enabled here because
    this function runs in worker context where network blips should NOT
    cause an analysis to be silently dropped — form check still rejects
    obvious garbage.
    """
    from stock_trading_system.utils.ticker_validator import (
        InvalidTickerError, normalize_and_validate_ticker,
    )

    try:
        v = normalize_and_validate_ticker(ticker, allow_quote_failure=True)
    except InvalidTickerError as e:
        raise ValueError(f"invalid ticker {ticker!r}: {e.reason}") from e

    t = v.canonical
    sess = store.find_session_by_ticker(t, user_id=user_id)
    if sess:
        return sess
    sid = store.create_ticker_session(t, start_date=start_date,
                                       start_capital=start_capital,
                                       config=config, user_id=user_id)
    logger.info("Created ticker session %s for %s (start=%s, user=%s)",
                sid, t, start_date, user_id)
    return store.get_session(sid)
