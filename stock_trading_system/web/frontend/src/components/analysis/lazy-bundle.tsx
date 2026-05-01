/**
 * Lazy-load barrel for the 8 analysis tab cards. Imported via
 * ``React.lazy(() => import("@/components/analysis/lazy-bundle"))`` so
 * the whole tab-card surface ends up in its own chunk. The default
 * export is a tiny dispatcher component the AnalysisPage uses to
 * render the right card by tab key.
 *
 * Each card module already exists as a top-level export from
 * ``@/components/analysis``; we re-import them here so the lazy chunk
 * is the seam, not the individual card files.
 */
import {
  OverviewCard, MarketCard, SentimentCard, NewsCard,
  FundamentalsCard, DebateCard, RiskCard, DecisionCard,
} from "@/components/analysis"

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TAB_CARD: Record<string, React.FC<{ data: any }>> = {
  "summary":            OverviewCard,
  "Market":             MarketCard,
  "Sentiment":          SentimentCard,
  "News":               NewsCard,
  "Fundamentals":       FundamentalsCard,
  "Investment Debate":  DebateCard,
  "Risk Assessment":    RiskCard,
  "Decision":           DecisionCard,
}

interface AnalysisCardsProps {
  tabKey: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any
}

export default function AnalysisCards({ tabKey, data }: AnalysisCardsProps) {
  const Comp = TAB_CARD[tabKey]
  if (!Comp) return null
  return <Comp data={data} />
}
