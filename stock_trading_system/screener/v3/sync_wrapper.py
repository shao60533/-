"""Sync wrapper that mirrors the legacy v1 ``StockScreener.screen()`` API.

hardening-iteration-v1 P3.1 step-2 — bridges v3's async, NL-query
pipeline into the v1 sync ``screen(market, strategy) → list[dict]``
shape so the three legacy call sites can flip without touching their
surrounding code:

  * ``stock_trading_system/web/app.py:72``  (``/api/screen``)
  * ``stock_trading_system/alerts/telegram_bot.py:288``  (``/screen`` cmd)
  * ``stock_trading_system/main.py:68``  (``stock screen`` CLI)

Step-3 (subsequent PR) flips those three imports; this module is the
contract step-3 will rely on.

Strategy → NL query mapping:
  growth          → "高成长股 美股 营收复合增长率 25%+"
  value           → "价值股 美股 低市盈率 高股息率"
  momentum        → "动量股 美股 近6个月强势 高交易量"
  low_volatility  → "低波动股 美股 防守型 高质量 蓝筹"

These defaults match the spirit of v1's STRATEGIES table; tune in
``_STRATEGY_TO_NL_QUERY`` once product confirms. The mapping lives in
ONE place so retraining the LLM prompt later only touches this file.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from stock_trading_system.utils import get_logger

logger = get_logger("screener.v3.sync_wrapper")


# v1 strategy id → NL query the v3 pipeline understands. Deliberately
# Chinese phrasing so the Qwen-trained NL parser (screener/v2/nl_parser)
# routes them to the same FilterSpec the legacy ``STRATEGIES`` constants
# implicitly described.
_STRATEGY_TO_NL_QUERY: dict[str, str] = {
    "growth": "高成长股 美股 营收复合增长率 25%+ 净利润同比增速 30%+",
    "value": "价值股 美股 低市盈率 PE<15 高股息率 股息率>3%",
    "momentum": "动量股 美股 近6个月涨幅 强势 高交易量 突破新高",
    "low_volatility": "低波动股 美股 防守型 高质量 蓝筹 Beta<0.8",
}


def screen_sync(
    config: dict,
    market: str = "us",
    strategy: str = "growth",
    candidate_n: int = 20,
    nl_query_override: str | None = None,
) -> list[dict]:
    """v1-compatible synchronous wrapper around v3 ScreenerV3Pipeline.

    Args:
        config: app config dict (for provider/model selection).
        market: ``"us"`` / ``"cn"`` / ``"all"`` — matches v1's ``market`` arg.
        strategy: ``"growth"`` / ``"value"`` / ``"momentum"`` / ``"low_volatility"``
            — v1's strategy ids; mapped to an NL query via
            ``_STRATEGY_TO_NL_QUERY``. ``nl_query_override`` skips the
            mapping for callers that already have a free-form query.
        candidate_n: pool size before guru evaluation (default 20).
        nl_query_override: optional escape hatch — when present, the
            ``strategy`` mapping is bypassed and the override is sent
            verbatim to v3. ``main.py`` CLI surfaces this so power users
            can drive v3 directly without picking a v1 preset.

    Returns:
        list of v1-shape dicts: ``[{ticker, name, sector, signal, summary,
        score}, ...]``. Empty list on pipeline failure (logged) — the
        legacy caller's "no results" branch handles it gracefully.

    Behaviour:
        Runs ``asyncio.run()`` internally — caller must NOT already be
        in an event loop. The two existing call sites (web + telegram
        + CLI) are all sync entry points so this is fine; worker
        threads should call ``await pipeline.run()`` directly.
    """
    nl_query = nl_query_override or _STRATEGY_TO_NL_QUERY.get(
        strategy, _STRATEGY_TO_NL_QUERY["growth"],
    )

    try:
        from stock_trading_system.screener.v3.pipeline import ScreenerV3Pipeline
    except ImportError as e:
        logger.error("v3 pipeline unavailable: %s", e)
        return []

    pipeline = ScreenerV3Pipeline(config=config)

    try:
        result = asyncio.run(pipeline.run(
            nl_query=nl_query,
            market=market,
            candidate_n=candidate_n,
            mode="classic",
            with_roundtable=False,
        ))
    except RuntimeError as e:
        # "asyncio.run() cannot be called from a running event loop"
        # surfaces here if a thread that already has a loop tries to
        # use the sync wrapper. Log + degrade rather than crash.
        logger.error("screen_sync invoked inside an event loop: %s", e)
        return []
    except Exception as e:  # noqa: BLE001
        logger.error("v3 pipeline failed: %s", e)
        return []

    return _v3_result_to_v1_list(result)


def _v3_result_to_v1_list(v3_result: dict) -> list[dict]:
    """Convert v3's rich result envelope to the v1 ``list[dict]`` shape.

    v3 returns:
        {"engine": "v3", "results": [{ticker, signal, votes, consensus, ...}],
         "metrics": {...}, ...}

    v1 expected:
        [{"ticker": str, "name": str, "sector": str,
          "signal": "BUY"|"SELL"|"HOLD", "summary": str, ...}]

    v1 callers don't expect ``votes`` / ``consensus`` / ``metrics`` so
    we flatten to the minimum surface and stash the v3 extras in a
    ``v3_meta`` key for advanced consumers (the React island ignores
    unknown keys).
    """
    if not isinstance(v3_result, dict):
        return []
    rows = v3_result.get("results") or []
    if not isinstance(rows, list):
        return []

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # v3's "signal" is one of "bullish" / "bearish" / "neutral" /
        # "split"; legacy v1 consumers expect "BUY" / "SELL" / "HOLD".
        v3_signal = (row.get("signal") or "").lower()
        v1_signal = {
            "bullish": "BUY",
            "bearish": "SELL",
            "neutral": "HOLD",
            "split": "HOLD",
        }.get(v3_signal, "HOLD")

        # v3's top_bull_argument / top_bear_argument is what v1 callers
        # show as the analyst "summary" text.
        summary = (
            row.get("top_bull_argument")
            or row.get("top_bear_argument")
            or row.get("summary")
            or ""
        )

        out.append({
            "ticker": row.get("ticker") or "",
            "name": row.get("name") or "",
            "sector": row.get("sector") or "",
            "signal": v1_signal,
            "summary": summary[:200] if isinstance(summary, str) else "",
            "score": row.get("score") or row.get("total_score") or 0,
            "v3_meta": {
                "votes": row.get("votes"),
                "consensus": row.get("consensus"),
                "confidence_range": row.get("confidence_range"),
            },
        })
    return out
