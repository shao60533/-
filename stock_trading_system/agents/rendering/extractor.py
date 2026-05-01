"""Convert finished analyzer reports into per-tab Pydantic structured cards.

Each tab is extracted independently with a quick_think LLM call. A single
tab failing yields ``None`` for that key — other tabs are unaffected. The
analyzer task is never blocked by an extraction failure (caller treats the
returned dict as best-effort).
"""

from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutTimeout,
    as_completed,
)
from typing import Any

from stock_trading_system.agents.rendering.schemas import (
    DebateCard,
    DecisionCard,
    FundamentalsCard,
    MarketCard,
    NewsCard,
    OverviewCard,
    RiskCard,
    SentimentCard,
)
from stock_trading_system.utils import get_logger

logger = get_logger("agents.rendering.extractor")


_SYS = (
    "You convert a stock-analysis report into a strict JSON schema. "
    "Use ONLY information present in the input — never invent prices, "
    "indicator values, dates, or news headlines. If a field is unknown, "
    "leave it null (or omit if optional). Verdict / synthesis fields are "
    "1–3 concise sentences; claim 1 sentence; evidence 1–2 sentences. "
    "Do NOT include personal-portfolio advice (sizing percentages tied to "
    "user holdings, personal entry timing). Technical objective price "
    "levels (SMA, support, resistance) are allowed."
)


class RenderingExtractor:
    """Extract 8 structured cards from an analyzer result.

    Per-tab failure is isolated: one tab's exception does not affect the
    others. The LLM client must implement ``with_structured_output(schema)``
    returning an object with an ``invoke(messages)`` method (LangChain
    contract — both ``ChatOpenAI`` and ``ChatGoogleGenerativeAI`` satisfy
    this).
    """

    def __init__(self, llm: Any, *, per_tab_timeout: float = 45.0):
        self._llm = llm
        self._timeout = per_tab_timeout

    def extract(self, result) -> dict[str, dict | None]:
        overview_input = self._build_overview_input(result)
        tasks: list[tuple[str, type, str]] = [
            ("summary",            OverviewCard,     overview_input),
            ("Market",             MarketCard,       getattr(result, "market_report", "") or ""),
            ("Sentiment",          SentimentCard,    getattr(result, "sentiment_report", "") or ""),
            ("News",               NewsCard,         getattr(result, "news_report", "") or ""),
            ("Fundamentals",       FundamentalsCard, getattr(result, "fundamentals_report", "") or ""),
            ("Investment Debate",  DebateCard,       str(getattr(result, "investment_debate", "") or "")),
            ("Risk Assessment",    RiskCard,         str(getattr(result, "risk_assessment", "") or "")),
            ("Decision",           DecisionCard,     str(getattr(result, "trade_decision", "") or "")),
        ]
        out: dict[str, dict | None] = {}
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="render-extract") as pool:
            futs = {
                pool.submit(self._extract_one, key, schema, prompt): key
                for (key, schema, prompt) in tasks
            }
            for fut in as_completed(futs):
                key = futs[fut]
                try:
                    obj = fut.result(timeout=self._timeout)
                    out[key] = (
                        obj.model_dump(exclude_none=False, mode="json")
                        if obj is not None else None
                    )
                except FutTimeout:
                    logger.warning("rendering extract %s timed out", key)
                    out[key] = None
                except Exception as e:  # noqa: BLE001
                    logger.warning("rendering extract %s failed: %s", key, e)
                    out[key] = None
        return out

    def _extract_one(self, key: str, schema, content: str):
        if not content or not content.strip():
            return None
        structured = self._llm.with_structured_output(schema)
        return structured.invoke([
            {"role": "system", "content": _SYS},
            {"role": "user",   "content": f"[REPORT — {key}]\n{content}"},
        ])

    @staticmethod
    def _build_overview_input(result) -> str:
        return "\n\n".join([
            f"## Market\n{getattr(result, 'market_report', '') or ''}",
            f"## Sentiment\n{getattr(result, 'sentiment_report', '') or ''}",
            f"## News\n{getattr(result, 'news_report', '') or ''}",
            f"## Fundamentals\n{getattr(result, 'fundamentals_report', '') or ''}",
            f"## Debate\n{getattr(result, 'investment_debate', '') or ''}",
            f"## Risk\n{getattr(result, 'risk_assessment', '') or ''}",
            f"## Decision\n{getattr(result, 'trade_decision', '') or ''}",
        ])
