/**
 * Lazy-load barrel for the 8 analysis tab cards.
 *
 * Loaded by ``AnalysisPage`` via ``React.lazy(() => import("@/components/analysis/lazy-bundle"))``
 * so the whole tab-card surface ends up in its own chunk.
 *
 * IMPORTANT — chunk-graph rules to keep this lazy chunk independent:
 *
 *   1. Import each card from its concrete file path. Do NOT import
 *      from the ``"@/components/analysis"`` barrel; that barrel also
 *      re-exports types that the analysis entry chunk consumes, and
 *      Rollup ends up putting the barrel module on the entry side,
 *      forcing this chunk to import back into the entry — a cycle
 *      that broke production /analysis/17 (lazy chunk's destructured
 *      imports resolved before the entry's bindings finished
 *      initialising, so cards saw ``undefined`` helpers and threw,
 *      producing the per-tab "结构化摘要暂不可用" fallback).
 *
 *   2. The defensive helpers (``normalizeCardForClient``) must only
 *      be imported from this chunk and from the cards themselves —
 *      NEVER from the analysis entry. ``AnalysisPage.tsx`` therefore
 *      passes raw ``rendering[tab]`` straight through and we
 *      normalise here, where it's safe.
 */
import { OverviewCard }     from "./OverviewCard"
import { MarketCard }       from "./MarketCard"
import { SentimentCard }    from "./SentimentCard"
import { NewsCard }         from "./NewsCard"
import { FundamentalsCard } from "./FundamentalsCard"
import { DebateCard }       from "./DebateCard"
import { RiskCard }         from "./RiskCard"
import { DecisionCard }     from "./DecisionCard"
import { normalizeCardForClient } from "./shared/defensive"

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
  // Raw value off ``detail.rendering[tab]`` — we re-normalise on the
  // client even though the backend already does, because production
  // rows that predate the backend normaliser still flow through here.
  data: unknown
}

/**
 * Dispatcher rendered inside a ``React.Suspense`` boundary. Returns
 * ``null`` (no DOM) when the tab key is unknown OR when normalize
 * collapses the payload to ``null`` (e.g. ``Market: "string"``). The
 * outer ``ErrorBoundary`` in AnalysisPage then never fires for
 * "unrecoverable" inputs — it stays armed only for genuine card-
 * internal exceptions, which the cards' own ``safeRecord`` /
 * ``safeText`` guards already rule out for known shapes.
 */
export default function AnalysisCards({ tabKey, data }: AnalysisCardsProps) {
  const Comp = TAB_CARD[tabKey]
  if (!Comp) return null
  const normalised = normalizeCardForClient(tabKey, data)
  if (!normalised) return null
  return <Comp data={normalised} />
}
