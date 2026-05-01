"""Per-tab failure isolation, hybrid data-source merge, and hard guards
for the v1.19.1 rendering extractor."""

from __future__ import annotations

import json

import pytest

from stock_trading_system.agents.rendering.extractor import RenderingExtractor
from stock_trading_system.agents.rendering.schemas import (
    Catalyst,
    DebateSynthesis,
    FundamentalsCard,
    Headline,
    KeyMetric,
    MarketCard,
    NewsCard,
    OverviewCard,
    Stance,
    Valuation,
)


def _overview_stub() -> OverviewCard:
    return OverviewCard(
        rating="Hold", action_direction="观察", confidence="low",
        key_metrics=[KeyMetric(label="x", value="y")],
        debate_synthesis=DebateSynthesis(
            aggressive=Stance(claim="a", evidence="b", limitation="c"),
            conservative=Stance(claim="a", evidence="b", limitation="c"),
            neutral=Stance(claim="a", evidence="b", limitation="c"),
            verdict="v",
        ),
        decision_drivers=[],
        one_line_takeaway="t",
    )


class _StubLLM:
    """LangChain-shaped stub LLM. Per-schema dispatch — News and
    Fundamentals get tailored returns so the hard-guard tests have
    something to check; the other six fall back to a permissive
    ``model_construct``."""

    def __init__(self, *, fail_schemas: tuple = (),
                 news_card: NewsCard | None = None,
                 fundamentals_card: FundamentalsCard | None = None):
        self._fail_schemas = set(fail_schemas)
        self._news_card = news_card
        self._fundamentals_card = fundamentals_card
        self.calls: list[str] = []

    def with_structured_output(self, schema):
        outer = self
        target_schema = schema

        class _S:
            def invoke(self, msgs):
                outer.calls.append(target_schema.__name__)
                if target_schema in outer._fail_schemas:
                    raise RuntimeError(f"forced fail {target_schema.__name__}")
                if target_schema is OverviewCard:
                    return _overview_stub()
                if target_schema is MarketCard:
                    return MarketCard(
                        trend="neutral", indicators=[],
                        support_resistance=[], patterns=[],
                        summary="ok",
                    )
                if target_schema is NewsCard and outer._news_card is not None:
                    return outer._news_card
                if (target_schema is FundamentalsCard
                        and outer._fundamentals_card is not None):
                    return outer._fundamentals_card
                return target_schema.model_construct()

        return _S()


class _DM:
    """Stub DataManager — feeds real fixtures into News + Fundamentals."""

    def __init__(self, *, fundamentals=None, news=None):
        self._f = fundamentals
        self._n = news

    def get_fundamentals(self, ticker):  # noqa: ARG002 — DataManager shape
        return self._f

    def get_news(self, ticker):  # noqa: ARG002 — DataManager shape
        return self._n


class _Result:
    market_report = "m"
    sentiment_report = "s"
    news_report = "n"
    fundamentals_report = "f"
    investment_debate = "d"
    risk_assessment = "r"
    trade_decision = "dec"


# ── 8-key sweep ──────────────────────────────────────────────────────────

def test_extractor_returns_8_keys():
    out = RenderingExtractor(_StubLLM()).extract(_Result(), ticker="X")
    assert set(out.keys()) == {
        "summary", "Market", "Sentiment", "News",
        "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
    }
    assert out["summary"]["rating"] == "Hold"
    assert out["Market"]["trend"] == "neutral"


def test_extractor_per_tab_failure_isolated():
    out = RenderingExtractor(_StubLLM(fail_schemas=(NewsCard,))).extract(
        _Result(), ticker="X",
    )
    # News falls back to (None) when there are no real headlines and the
    # LLM raised. Other tabs continue to render.
    assert out["News"] is None
    assert out["summary"] is not None
    assert out["Market"] is not None


def test_extractor_skips_empty_input():
    class _Empty:
        market_report = ""
        sentiment_report = ""
        news_report = ""
        fundamentals_report = ""
        investment_debate = ""
        risk_assessment = ""
        trade_decision = ""

    out = RenderingExtractor(_StubLLM()).extract(_Empty(), ticker="X")
    assert out["Market"] is None
    assert out["News"] is None
    assert out["Fundamentals"] is None


def test_extractor_serializes_to_dict_with_mode_json():
    out = RenderingExtractor(_StubLLM()).extract(_Result(), ticker="X")
    blob = json.dumps(out, ensure_ascii=False)
    again = json.loads(blob)
    assert again["summary"]["rating"] == "Hold"


# ── News hard guards ─────────────────────────────────────────────────────

@pytest.fixture
def real_news() -> list[dict]:
    return [
        {"title": "T1", "source": "Reuters", "published": "2026-04-30"},
        {"title": "T2", "source": "Bloomberg", "published": "2026-04-29"},
    ]


def test_news_hybrid_real_headlines_kept_and_tagged(real_news):
    """LLM returns real titles + sentiment tags → output preserves real
    metadata and overlays sentiment/impact from the LLM."""
    news_card = NewsCard(
        headlines=[
            Headline(title="T1", sentiment="bullish", impact="high"),
            Headline(title="T2", sentiment="bearish", impact="medium"),
        ],
        catalysts=[Catalyst(kind="earnings", summary="Q1 beat")],
        summary="Mixed but actionable.",
    )
    dm = _DM(news=real_news)
    extractor = RenderingExtractor(_StubLLM(news_card=news_card),
                                    data_manager=dm)
    out = extractor.extract(_Result(), ticker="AAPL")
    news = out["News"]
    titles = [h["title"] for h in news["headlines"]]
    assert titles == ["T1", "T2"]
    # Sentiment + impact merged from LLM.
    assert news["headlines"][0]["sentiment"] == "bullish"
    assert news["headlines"][0]["impact"] == "high"
    # Real metadata preserved.
    assert news["headlines"][0]["source"] == "Reuters"
    assert news["headlines"][0]["date"] == "2026-04-30"
    # Catalyst + summary survive.
    assert news["catalysts"][0]["kind"] == "earnings"
    assert "Mixed" in news["summary"]


def test_news_hard_guard_drops_fabricated_headlines(real_news, caplog):
    """An LLM that hallucinates a fresh title gets that headline dropped."""
    news_card = NewsCard(
        headlines=[
            Headline(title="T1", sentiment="bullish", impact="high"),
            # FABRICATED — title not in real_news.
            Headline(title="MADE UP MEGA SCANDAL",
                     sentiment="bearish", impact="high"),
        ],
        summary="x",
    )
    dm = _DM(news=real_news)
    extractor = RenderingExtractor(_StubLLM(news_card=news_card),
                                    data_manager=dm)
    import logging
    caplog.set_level(logging.WARNING)
    out = extractor.extract(_Result(), ticker="AAPL")
    titles = [h["title"] for h in out["News"]["headlines"]]
    # Fabrication dropped; both real titles preserved.
    assert "MADE UP MEGA SCANDAL" not in titles
    assert set(titles) == {"T1", "T2"}
    # Hard guard logs a warning so prod operators can investigate.
    assert any("hard guard" in (r.message or "").lower()
               for r in caplog.records)


def test_news_hard_guard_appends_real_headlines_llm_forgot(real_news):
    """LLM only labels T1; T2 must still appear in output (untagged)."""
    news_card = NewsCard(
        headlines=[Headline(title="T1", sentiment="bullish", impact="high")],
        summary="x",
    )
    dm = _DM(news=real_news)
    extractor = RenderingExtractor(_StubLLM(news_card=news_card),
                                    data_manager=dm)
    out = extractor.extract(_Result(), ticker="AAPL")
    titles = [h["title"] for h in out["News"]["headlines"]]
    assert titles == ["T1", "T2"]
    # T1 inherits LLM tag; T2 falls back to neutral/medium defaults.
    assert out["News"]["headlines"][0]["sentiment"] == "bullish"
    assert out["News"]["headlines"][1]["sentiment"] == "neutral"


def test_news_llm_failure_returns_real_headlines_only(real_news):
    """LLM raises → real headlines still surface; no crash."""
    dm = _DM(news=real_news)
    extractor = RenderingExtractor(
        _StubLLM(fail_schemas=(NewsCard,)), data_manager=dm,
    )
    out = extractor.extract(_Result(), ticker="AAPL")
    news = out["News"]
    assert [h["title"] for h in news["headlines"]] == ["T1", "T2"]
    assert news["catalysts"] == []
    assert news["summary"] == ""


# ── Fundamentals hard guards ────────────────────────────────────────────

REAL_FUNDAMENTALS_INFO = {
    "trailingPE": 28.5, "priceToBook": 6.1, "priceToSalesTrailing12Months": 7.2,
    "enterpriseToEbitda": 21.0, "pegRatio": 1.8,
    "returnOnEquity": 0.31, "returnOnAssets": 0.21,
    "debtToEquity": 105.0, "currentRatio": 1.4, "quickRatio": 0.9,
    "revenueGrowth": 0.18, "earningsGrowth": 0.25, "freeCashflowGrowth": 0.12,
    "grossMargins": 0.45, "operatingMargins": 0.32,
    "sector": "Technology",
}


def test_fundamentals_hybrid_keeps_real_numbers_lets_llm_qualify():
    """LLM only contributes vs_industry / quality_score / summary."""
    fcard = FundamentalsCard(
        valuation=Valuation(vs_industry="rich vs sector median"),
        quality_score=4,
        summary="High quality, premium valuation.",
    )
    dm = _DM(fundamentals=REAL_FUNDAMENTALS_INFO)
    extractor = RenderingExtractor(_StubLLM(fundamentals_card=fcard),
                                    data_manager=dm)
    out = extractor.extract(_Result(), ticker="AAPL")
    f = out["Fundamentals"]
    # Real numbers preserved verbatim.
    assert f["valuation"]["pe"] == 28.5
    assert f["valuation"]["pb"] == 6.1
    assert f["growth"]["revenue_yoy_pct"] == 18.0
    assert f["profitability"]["roe_pct"] == 31.0
    # LLM-only fields surfaced.
    assert f["valuation"]["vs_industry"] == "rich vs sector median"
    assert f["quality_score"] == 4
    assert "premium" in f["summary"]


def test_fundamentals_hard_guard_overrides_llm_pe_attempt():
    """If the LLM 'rounds' PE down to a friendlier 25.0, the hard guard
    snaps it back to the real 28.5."""
    fcard = FundamentalsCard(
        valuation=Valuation(pe=25.0, pb=5.0,  # ← LLM lies.
                            vs_industry="industry-aligned"),
        growth={"revenue_yoy_pct": 99.9},  # ← LLM lies.
        quality_score=5,
        summary="Inflated story.",
    )
    dm = _DM(fundamentals=REAL_FUNDAMENTALS_INFO)
    extractor = RenderingExtractor(_StubLLM(fundamentals_card=fcard),
                                    data_manager=dm)
    out = extractor.extract(_Result(), ticker="AAPL")
    f = out["Fundamentals"]
    # Hard guard snaps numbers back to real-data values.
    assert f["valuation"]["pe"] == 28.5
    assert f["valuation"]["pb"] == 6.1
    assert f["growth"]["revenue_yoy_pct"] == 18.0
    # vs_industry survives — it's a qualitative LLM-only field.
    assert f["valuation"]["vs_industry"] == "industry-aligned"


def test_fundamentals_falls_back_to_llm_when_data_manager_missing():
    """Without a data_manager, Fundamentals goes pure-LLM (v1.0 behavior)."""
    extractor = RenderingExtractor(_StubLLM(), data_manager=None)
    out = extractor.extract(_Result(), ticker="AAPL")
    # Stub returns ``model_construct`` — call still succeeds and yields a
    # dict shaped like FundamentalsCard.
    assert isinstance(out["Fundamentals"], dict)


def test_fundamentals_llm_failure_returns_real_numbers_only():
    """LLM raises → real numeric blocks still rendered with default qualifiers."""
    dm = _DM(fundamentals=REAL_FUNDAMENTALS_INFO)
    extractor = RenderingExtractor(
        _StubLLM(fail_schemas=(FundamentalsCard,)), data_manager=dm,
    )
    out = extractor.extract(_Result(), ticker="AAPL")
    f = out["Fundamentals"]
    assert f["valuation"]["pe"] == 28.5
    assert f["growth"]["revenue_yoy_pct"] == 18.0
    assert f["quality_score"] == 3   # default
    assert f["summary"] == ""        # blank — LLM never produced it
