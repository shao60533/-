// Mirrors stock_trading_system/agents/rendering/schemas.py.
// Source of truth lives in Python; keep the two in lock-step. When a
// schema field changes, regenerate (or hand-edit) the matching field
// here — TypeScript can't import Pydantic.

export interface KeyMetric {
  label: string
  value: string
  tone?: "positive" | "negative" | "neutral"
  hint?: string | null
}

export interface Stance {
  claim: string
  evidence: string
  limitation: string
}

export interface Argument {
  claim: string
  evidence: string
  weight?: "primary" | "secondary" | "tertiary"
}

export type Rating =
  | "Strong Buy" | "Buy" | "Overweight" | "Hold"
  | "Underweight" | "Sell" | "Strong Sell"

export type Confidence = "high" | "medium" | "low"
export type Trend = "bullish" | "bearish" | "neutral" | "range"
export type Mood = "extreme_fear" | "fear" | "neutral" | "greed" | "extreme_greed"
export type Action = "BUY" | "SELL" | "HOLD" | "REDUCE" | "ADD" | "WAIT"
export type Horizon = "intraday" | "swing" | "short" | "medium" | "long"

// 1. Overview -----------------------------------------------------------
export interface DebateSynthesis {
  aggressive: Stance
  conservative: Stance
  neutral: Stance
  verdict: string
}

export interface DecisionDriver {
  headline: string
  detail: string
}

export interface OverviewCardData {
  rating: Rating
  action_direction: string
  confidence: Confidence
  key_metrics?: KeyMetric[]
  debate_synthesis?: DebateSynthesis | null
  decision_drivers?: DecisionDriver[]
  one_line_takeaway: string
}

// 2. Market -------------------------------------------------------------
export interface TechnicalIndicator {
  name: string
  value: string
  signal: "bullish" | "bearish" | "neutral"
}

export interface PriceLevel {
  price: number
  kind: "support" | "resistance" | "pivot"
  strength?: "strong" | "medium" | "weak"
  note?: string | null
}

export interface MarketCardData {
  trend: Trend
  indicators?: TechnicalIndicator[]
  support_resistance?: PriceLevel[]
  patterns?: string[]
  summary: string
}

// 3. Sentiment ----------------------------------------------------------
export interface SentimentDriver {
  source: "news" | "social" | "options" | "analyst" | "insider"
  theme: string
  polarity: "bullish" | "bearish" | "mixed"
}

export interface SentimentCardData {
  mood: Mood
  mood_score: number
  drivers?: SentimentDriver[]
  contrarian_signal?: boolean
  contrarian_reason?: string | null
  summary: string
}

// 4. News ---------------------------------------------------------------
export interface Headline {
  title: string
  source?: string | null
  date?: string | null
  sentiment?: "bullish" | "bearish" | "neutral"
  impact?: "high" | "medium" | "low"
}

export interface Catalyst {
  kind: "earnings" | "macro" | "sector" | "company" | "regulatory"
  summary: string
  date?: string | null
}

export interface NewsCardData {
  headlines?: Headline[]
  catalysts?: Catalyst[]
  summary: string
}

// 5. Fundamentals -------------------------------------------------------
export interface Valuation {
  pe?: number | null; pb?: number | null; ps?: number | null
  ev_ebitda?: number | null; peg?: number | null
  vs_industry?: string | null
}
export interface Growth {
  revenue_yoy_pct?: number | null
  eps_yoy_pct?: number | null
  fcf_yoy_pct?: number | null
}
export interface Profitability {
  gross_margin_pct?: number | null
  op_margin_pct?: number | null
  roe_pct?: number | null
  roic_pct?: number | null
}
export interface BalanceSheet {
  debt_to_equity?: number | null
  current_ratio?: number | null
  cash_ratio?: number | null
}

export interface FundamentalsCardData {
  valuation?: Valuation
  growth?: Growth
  profitability?: Profitability
  balance_sheet?: BalanceSheet
  quality_score?: number  // 1..5
  summary: string
}

// 6. Debate -------------------------------------------------------------
export interface DebateCardData {
  bull_arguments?: Argument[]
  bear_arguments?: Argument[]
  neutral_synthesis: string
  verdict: "bull" | "bear" | "draw"
  key_disagreement: string
}

// 7. Risk ---------------------------------------------------------------
export interface TopRisk {
  risk: string
  probability: "high" | "medium" | "low"
  severity: "high" | "medium" | "low"
  mitigation?: string | null
}

export interface RiskCardData {
  aggressive: Stance
  conservative: Stance
  neutral: Stance
  verdict: string
  top_risks?: TopRisk[]
}

// 8. Decision -----------------------------------------------------------
export interface PriceZone { low: number; high: number }
export interface TakeProfitLevel {
  price: number
  weight_pct: number
  rationale?: string | null
}
export interface AlternativeScenario {
  condition: string
  action: string
}

export interface DecisionCardData {
  final_action: Action
  conviction: Confidence
  entry_zone?: PriceZone | null
  structural_stop?: number | null
  take_profit_levels?: TakeProfitLevel[]
  time_horizon: Horizon
  preconditions?: string[]
  exit_conditions?: string[]
  alternative_scenarios?: AlternativeScenario[]
  one_line_summary: string
}

// Aggregate for AnalysisDetail.rendering -------------------------------
export type RenderingDict = Partial<{
  summary: OverviewCardData
  Market: MarketCardData
  Sentiment: SentimentCardData
  News: NewsCardData
  Fundamentals: FundamentalsCardData
  "Investment Debate": DebateCardData
  "Risk Assessment": RiskCardData
  Decision: DecisionCardData
}>
