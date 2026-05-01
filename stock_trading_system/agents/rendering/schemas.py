"""Pydantic schemas for AI analysis structured rendering (8 tabs).

These schemas hold ONLY shared-research content. Per-user advice (personal
position sizing, entry, stop, take profit weights driven by holdings) lives
in ``user_analysis_advice``. Technical objective price levels (e.g. 200-SMA
support, Bollinger upper band) are shared research and may appear here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Shared helpers ────────────────────────────────────────────────────────

class KeyMetric(BaseModel):
    label: str
    value: str
    tone: Literal["positive", "negative", "neutral"] = "neutral"
    hint: str | None = None


class Stance(BaseModel):
    claim: str
    evidence: str
    limitation: str


class Argument(BaseModel):
    claim: str
    evidence: str
    weight: Literal["primary", "secondary", "tertiary"] = "secondary"


RatingLiteral = Literal[
    "Strong Buy", "Buy", "Overweight", "Hold",
    "Underweight", "Sell", "Strong Sell",
]
ConfLiteral = Literal["high", "medium", "low"]
TrendLiteral = Literal["bullish", "bearish", "neutral", "range"]
MoodLiteral = Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
ActionLiteral = Literal["BUY", "SELL", "HOLD", "REDUCE", "ADD", "WAIT"]
HorizonLiteral = Literal["intraday", "swing", "short", "medium", "long"]


# ── 1. Overview ──────────────────────────────────────────────────────────

class DebateSynthesis(BaseModel):
    aggressive: Stance
    conservative: Stance
    neutral: Stance
    verdict: str


class DecisionDriver(BaseModel):
    headline: str
    detail: str


class OverviewCard(BaseModel):
    rating: RatingLiteral
    action_direction: str
    confidence: ConfLiteral
    key_metrics: list[KeyMetric] = Field(default_factory=list, max_length=6)
    debate_synthesis: DebateSynthesis | None = None
    decision_drivers: list[DecisionDriver] = Field(default_factory=list, max_length=5)
    one_line_takeaway: str


# ── 2. Market ────────────────────────────────────────────────────────────

class TechnicalIndicator(BaseModel):
    name: str
    value: str
    signal: Literal["bullish", "bearish", "neutral"]


class PriceLevel(BaseModel):
    price: float
    kind: Literal["support", "resistance", "pivot"]
    strength: Literal["strong", "medium", "weak"] = "medium"
    note: str | None = None


class MarketCard(BaseModel):
    trend: TrendLiteral
    indicators: list[TechnicalIndicator] = Field(default_factory=list, max_length=8)
    support_resistance: list[PriceLevel] = Field(default_factory=list, max_length=6)
    patterns: list[str] = Field(default_factory=list, max_length=4)
    summary: str


# ── 3. Sentiment ─────────────────────────────────────────────────────────

class SentimentDriver(BaseModel):
    source: Literal["news", "social", "options", "analyst", "insider"]
    theme: str
    polarity: Literal["bullish", "bearish", "mixed"]


class SentimentCard(BaseModel):
    mood: MoodLiteral
    mood_score: int = Field(..., ge=-100, le=100)
    drivers: list[SentimentDriver] = Field(default_factory=list, max_length=5)
    contrarian_signal: bool = False
    contrarian_reason: str | None = None
    summary: str


# ── 4. News ──────────────────────────────────────────────────────────────

class Headline(BaseModel):
    title: str
    source: str | None = None
    date: str | None = None
    sentiment: Literal["bullish", "bearish", "neutral"] = "neutral"
    impact: Literal["high", "medium", "low"] = "medium"


class Catalyst(BaseModel):
    kind: Literal["earnings", "macro", "sector", "company", "regulatory"]
    summary: str
    date: str | None = None


class NewsCard(BaseModel):
    headlines: list[Headline] = Field(default_factory=list, max_length=8)
    catalysts: list[Catalyst] = Field(default_factory=list, max_length=5)
    summary: str


# ── 5. Fundamentals ──────────────────────────────────────────────────────

class Valuation(BaseModel):
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    peg: float | None = None
    vs_industry: str | None = None


class Growth(BaseModel):
    revenue_yoy_pct: float | None = None
    eps_yoy_pct: float | None = None
    fcf_yoy_pct: float | None = None


class Profitability(BaseModel):
    gross_margin_pct: float | None = None
    op_margin_pct: float | None = None
    roe_pct: float | None = None
    roic_pct: float | None = None


class BalanceSheet(BaseModel):
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    cash_ratio: float | None = None


class FundamentalsCard(BaseModel):
    valuation: Valuation = Field(default_factory=Valuation)
    growth: Growth = Field(default_factory=Growth)
    profitability: Profitability = Field(default_factory=Profitability)
    balance_sheet: BalanceSheet = Field(default_factory=BalanceSheet)
    quality_score: int = Field(3, ge=1, le=5)
    summary: str


# ── 6. Investment Debate ─────────────────────────────────────────────────

class DebateCard(BaseModel):
    bull_arguments: list[Argument] = Field(default_factory=list, max_length=5)
    bear_arguments: list[Argument] = Field(default_factory=list, max_length=5)
    neutral_synthesis: str
    verdict: Literal["bull", "bear", "draw"]
    key_disagreement: str


# ── 7. Risk Assessment ───────────────────────────────────────────────────

class TopRisk(BaseModel):
    risk: str
    probability: Literal["high", "medium", "low"]
    severity: Literal["high", "medium", "low"]
    mitigation: str | None = None


class RiskCard(BaseModel):
    aggressive: Stance
    conservative: Stance
    neutral: Stance
    verdict: str
    top_risks: list[TopRisk] = Field(default_factory=list, max_length=5)


# ── 8. Decision ──────────────────────────────────────────────────────────

class PriceZone(BaseModel):
    low: float
    high: float


class TakeProfitLevel(BaseModel):
    price: float
    weight_pct: int = Field(..., ge=1, le=100)
    rationale: str | None = None


class AlternativeScenario(BaseModel):
    condition: str
    action: str


class DecisionCard(BaseModel):
    final_action: ActionLiteral
    conviction: ConfLiteral
    entry_zone: PriceZone | None = None
    structural_stop: float | None = None
    take_profit_levels: list[TakeProfitLevel] = Field(default_factory=list, max_length=4)
    time_horizon: HorizonLiteral
    preconditions: list[str] = Field(default_factory=list, max_length=4)
    exit_conditions: list[str] = Field(default_factory=list, max_length=4)
    alternative_scenarios: list[AlternativeScenario] = Field(default_factory=list, max_length=3)
    one_line_summary: str


# ── Tab key registry ─────────────────────────────────────────────────────

TAB_SCHEMA: dict[str, type[BaseModel]] = {
    "summary":            OverviewCard,
    "Market":             MarketCard,
    "Sentiment":          SentimentCard,
    "News":               NewsCard,
    "Fundamentals":       FundamentalsCard,
    "Investment Debate":  DebateCard,
    "Risk Assessment":    RiskCard,
    "Decision":           DecisionCard,
}
