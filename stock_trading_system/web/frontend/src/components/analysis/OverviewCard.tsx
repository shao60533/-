import { Flame, Shield, Scale, MapPin } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { OverviewCardData } from "./types"
import { RatingBadge } from "./shared/RatingBadge"
import { ConfidenceMeter } from "./shared/ConfidenceMeter"
import { KpiRow } from "./shared/KpiRow"
import { StanceCard } from "./shared/StanceCard"

export function OverviewCard({ data }: { data: OverviewCardData }) {
  return (
    <div className="space-y-4">
      {/* Decision banner */}
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <RatingBadge rating={data.rating} />
            <ConfidenceMeter level={data.confidence} />
          </div>
          <div className="flex items-start gap-2 text-sm">
            <MapPin className="h-4 w-4 text-[var(--color-accent-blue)] mt-0.5 shrink-0" />
            <span>{data.action_direction}</span>
          </div>
          <KpiRow items={data.key_metrics} />
        </CardContent>
      </Card>

      {/* Three-stance debate synthesis */}
      {data.debate_synthesis && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">三派辩论综合</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-3">
              <StanceCard
                title="激进派" icon={<Flame className="h-4 w-4" />}
                stance={data.debate_synthesis.aggressive} accent="aggressive" />
              <StanceCard
                title="保守派" icon={<Shield className="h-4 w-4" />}
                stance={data.debate_synthesis.conservative} accent="conservative" />
              <StanceCard
                title="中立派" icon={<Scale className="h-4 w-4" />}
                stance={data.debate_synthesis.neutral} accent="neutral" />
            </div>
            <div className="rounded border-l-4 border-primary bg-primary/5 px-3 py-2 text-sm">
              <span className="font-semibold mr-2">综合判断:</span>
              {data.debate_synthesis.verdict}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Decision drivers */}
      {data.decision_drivers && data.decision_drivers.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">核心决策依据</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.decision_drivers.map((d, i) => (
              <div key={i} className="flex gap-3 items-start">
                <span className="font-mono text-lg text-primary leading-none mt-0.5">
                  {i + 1}
                </span>
                <div>
                  <div className="font-semibold text-sm">{d.headline}</div>
                  <div className="text-xs text-muted-foreground leading-relaxed mt-0.5">
                    {d.detail}
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.one_line_takeaway && (
        <div className="text-center text-sm text-muted-foreground italic">
          “{data.one_line_takeaway}”
        </div>
      )}
    </div>
  )
}
