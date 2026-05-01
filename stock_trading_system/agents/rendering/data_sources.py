"""Real data fetchers for the v1.19.1 News / Fundamentals tabs.

The v1.19.0 extractor asked the LLM to recover quantitative facts from
its own free-text reports. That produced hallucinated PE ratios. v1.19.1
short-circuits the numeric blocks to ``DataManager`` providers (yfinance
/ Polygon / IB / akshare); the LLM is left to do what it's good at:
sentiment labelling, summaries, and catalyst extraction. Hard guards in
:mod:`extractor` then overwrite anything the LLM tried to mutate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from stock_trading_system.agents.rendering.schemas import (
    BalanceSheet,
    Growth,
    Headline,
    Profitability,
    Valuation,
)
from stock_trading_system.utils import get_logger

logger = get_logger("agents.rendering.data_sources")


def fetch_fundamentals_facts(ticker: str, data_manager) -> dict:
    """Pull fundamentals from the active provider into the four sub-blocks.

    Missing fields stay ``None`` — the schema tolerates that and the UI
    skips empty rows. Returns an empty dict on hard provider failure so
    the extractor can fall back to pure-LLM mode.
    """
    if data_manager is None:
        return {}
    try:
        info = data_manager.get_fundamentals(ticker) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_fundamentals_facts(%s) failed: %s", ticker, e)
        return {}
    if not isinstance(info, dict):
        return {}

    val = Valuation(
        pe=_safe(info.get("trailingPE")),
        pb=_safe(info.get("priceToBook")),
        ps=_safe(info.get("priceToSalesTrailing12Months")),
        ev_ebitda=_safe(info.get("enterpriseToEbitda")),
        peg=_safe(info.get("pegRatio") or info.get("trailingPegRatio")),
    )
    growth = Growth(
        revenue_yoy_pct=_pct(info.get("revenueGrowth")),
        eps_yoy_pct=_pct(info.get("earningsGrowth")),
        fcf_yoy_pct=_pct(info.get("freeCashflowGrowth")),
    )
    prof = Profitability(
        gross_margin_pct=_pct(info.get("grossMargins")),
        op_margin_pct=_pct(info.get("operatingMargins")),
        roe_pct=_pct(info.get("returnOnEquity")),
        roic_pct=_pct(info.get("returnOnAssets")),
    )
    bs = BalanceSheet(
        debt_to_equity=_safe(info.get("debtToEquity")),
        current_ratio=_safe(info.get("currentRatio")),
        cash_ratio=_safe(info.get("quickRatio")),
    )
    return {
        "valuation": val.model_dump(),
        "growth": growth.model_dump(),
        "profitability": prof.model_dump(),
        "balance_sheet": bs.model_dump(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
    }


def fetch_news_headlines(ticker: str, data_manager,
                          limit: int = 8) -> list[dict]:
    """Pull up to ``limit`` news headlines as immutable real-data dicts.

    Sentiment / impact start as ``"neutral"`` / ``"medium"`` — the LLM
    enrichment step in :class:`RenderingExtractor` may upgrade them, but
    the title / source / date are frozen here so the hard guard can
    detect (and drop) any LLM-emitted fabrication.
    """
    if data_manager is None:
        return []
    try:
        items = data_manager.get_news(ticker) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_news_headlines(%s) failed: %s", ticker, e)
        return []
    out: list[dict] = []
    for n in items[:limit]:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "").strip()
        if not title:
            continue
        out.append(Headline(
            title=title,
            source=(str(n.get("source") or "").strip() or None),
            date=_normalize_date(
                n.get("published") or n.get("date") or n.get("publishedAt")
            ),
            sentiment="neutral",
            impact="medium",
        ).model_dump())
    return out


# ── helpers ──────────────────────────────────────────────────────────────

def _safe(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN check without numpy dep
        return None
    return v


def _pct(x) -> float | None:
    """Convert a 0..1 ratio (yfinance returns these as decimals) to percent."""
    v = _safe(x)
    return round(v * 100, 2) if v is not None else None


def _normalize_date(raw) -> str | None:
    """Best-effort ``YYYY-MM-DD`` from epoch / ISO / common date forms."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return (
                datetime.fromtimestamp(int(s), tz=timezone.utc)
                .strftime("%Y-%m-%d")
            )
        except (ValueError, OSError) as e:
            logger.warning("epoch parse failed for %r: %s", s, e)
            return None
    # ISO-8601 / YYYY-MM-DD prefix → first 10 chars suffice when valid.
    head = s[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return None
    return head
