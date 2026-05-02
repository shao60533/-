import { Flame, Shield, Scale, MapPin, ScrollText } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { OverviewCardData, DecisionDriver, KeyMetric, Stance } from "./types"
import { RatingBadge } from "./shared/RatingBadge"
import { ConfidenceMeter } from "./shared/ConfidenceMeter"
import { KpiRow } from "./shared/KpiRow"
import { StanceCard } from "./shared/StanceCard"
import { isRecord, safeRecord, nonEmptyStr, safeText } from "./shared/defensive"

interface OverviewCardProps {
  data: OverviewCardData | null | undefined
  /**
   * Optional execution summary surfaced from ``detail.executive_summary``
   * (paper-trade v1.3 F3 LLM-extracted column on ``analysis_history``).
   * Lives on the detail object, NOT inside ``rendering.summary`` Pydantic
   * schema — passed via prop to keep the schema layer untouched.
   */
  executiveSummary?: string | null
}

/**
 * Overview tab — the most-broken card on production /analysis/17.
 *
 * Defensive contract (every layer below assumes upstream gave us slop):
 *   * ``data`` may be an array, string, null — collapse to ``null``.
 *   * ``debate_synthesis`` may be an array/string — collapse to ``null``.
 *   * Each stance inside the synthesis may be string/array — drop it
 *     individually so the other two stances still render.
 *   * ``decision_drivers`` / ``key_metrics`` may contain string/null
 *     items — keep only records so children never see a non-object.
 */
export function OverviewCard({ data, executiveSummary }: OverviewCardProps) {
  // ``typeof === "object"`` was the bug: arrays + null both pass it,
  // and the rest of this function then read ``.rating`` / ``.confidence``
  // off an array, producing undefined, which the badges tolerated —
  // but ``data.debate_synthesis`` on an array's prototype chain made
  // ``synth`` truthy with no ``.aggressive`` field, throwing inside
  // StanceCard. ``safeRecord`` collapses all of that to a clean null.
  const rec = safeRecord(data)
  if (!rec) return null

  const synth = safeRecord(rec.debate_synthesis)
  // Each stance must be a record on its own, or StanceCard's
  // ``stance.claim`` access returns garbage on a string/array.
  const aggressive = synth ? (safeRecord(synth.aggressive) as Stance | null) : null
  const conservative = synth ? (safeRecord(synth.conservative) as Stance | null) : null
  const neutral = synth ? (safeRecord(synth.neutral) as Stance | null) : null

  // Note: ``Record<string, unknown>`` doesn't statically satisfy the
  // narrow Pydantic-mirrored interfaces — the LLM can omit any field.
  // We cast through ``unknown`` because every downstream read goes
  // through ``safeText`` / optional chaining, so a missing ``headline``
  // collapses to ``""`` rather than crashing.
  const drivers = (Array.isArray(rec.decision_drivers) ? rec.decision_drivers : [])
    .filter(isRecord) as unknown as DecisionDriver[]
  const keyMetrics = (Array.isArray(rec.key_metrics) ? rec.key_metrics : [])
    .filter(isRecord) as unknown as KeyMetric[]

  return (
    <div className="space-y-4">
      {/* Decision banner */}
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <RatingBadge rating={typeof rec.rating === "string" ? rec.rating : null} />
            <ConfidenceMeter level={typeof rec.confidence === "string" ? rec.confidence : null} />
          </div>
          {nonEmptyStr(rec.action_direction) && (
            <div className="flex items-start gap-2 text-sm">
              <MapPin className="h-4 w-4 text-[var(--color-accent-blue)] mt-0.5 shrink-0" />
              <span>{safeText(rec.action_direction)}</span>
            </div>
          )}
          {/* v1.6: Executive Summary block — surfaces detail.executive_summary
              (paper-trade v1.3 F3 column) as the structured "操作建议".
              Sits between action_direction and KpiRow per design §14.2.
              Hidden when prop missing / empty / whitespace-only via
              ``nonEmptyStr`` (which trims) so legacy rows without the
              column collapse the banner cleanly. */}
          {nonEmptyStr(executiveSummary) && (
            <div
              data-testid="executive-summary"
              className="rounded border-l-4 border-primary/60 bg-primary/5 px-3 py-2"
            >
              <div className="flex items-center gap-1.5 mb-1 text-xs font-semibold text-[var(--color-accent-blue)]">
                <ScrollText className="h-3.5 w-3.5" />
                执行总结
              </div>
              <div className="text-sm leading-relaxed line-clamp-4">
                {safeText(executiveSummary)}
              </div>
            </div>
          )}
          <KpiRow items={keyMetrics} />
        </CardContent>
      </Card>

      {/* Three-stance debate synthesis — guarded so a partial object
          (verdict only, no aggressive stance, etc.) still renders. */}
      {synth && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">三派辩论综合</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              <StanceCard
                title="激进派" icon={<Flame className="h-4 w-4" />}
                stance={aggressive} accent="aggressive" />
              <StanceCard
                title="保守派" icon={<Shield className="h-4 w-4" />}
                stance={conservative} accent="conservative" />
              <StanceCard
                title="中立派" icon={<Scale className="h-4 w-4" />}
                stance={neutral} accent="neutral" />
            </div>
            {nonEmptyStr(synth.verdict) && (
              <div className="rounded border-l-4 border-primary bg-primary/5 px-3 py-2 text-sm">
                <span className="font-semibold mr-2">综合判断:</span>
                {safeText(synth.verdict)}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Decision drivers — array items already filtered to records, so
          ``d.headline`` access never lands on a string/null. */}
      {drivers.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">核心决策依据</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {drivers.map((d, i) => (
              <div key={i} className="flex gap-3 items-start">
                <span className="font-mono text-lg text-primary leading-none mt-0.5">
                  {i + 1}
                </span>
                <div>
                  <div className="font-semibold text-sm">{safeText(d.headline)}</div>
                  {nonEmptyStr(d.detail) && (
                    <div className="text-xs text-muted-foreground leading-relaxed mt-0.5">
                      {safeText(d.detail)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {nonEmptyStr(rec.one_line_takeaway) && (
        <div className="text-center text-sm text-muted-foreground italic">
          “{safeText(rec.one_line_takeaway)}”
        </div>
      )}
    </div>
  )
}
