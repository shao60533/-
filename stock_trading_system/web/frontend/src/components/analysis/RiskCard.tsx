import { Flame, Shield, Scale } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { RiskCardData, TopRisk, Stance } from "./types"
import { StanceCard } from "./shared/StanceCard"
import { safeArray, nonEmptyStr, safeText, isRecord, safeRecord } from "./shared/defensive"

const PROB_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" }

// Color the (probability × severity) cell so the user can scan severity at a glance.
function cellTone(prob: unknown, sev: unknown): string {
  const score =
    (prob === "high" ? 3 : prob === "medium" ? 2 : 1) +
    (sev === "high" ? 3 : sev === "medium" ? 2 : 1)
  if (score >= 5) return "bg-red-600/30 text-red-200 border-red-500/40"
  if (score >= 4) return "bg-amber-600/25 text-amber-200 border-amber-500/40"
  return "bg-zinc-600/20 text-zinc-300 border-zinc-500/30"
}

export function RiskCard({ data }: { data: RiskCardData | null | undefined }) {
  const rec = safeRecord(data)
  if (!rec) return null
  const aggressive = safeRecord(rec.aggressive) as Stance | null
  const conservative = safeRecord(rec.conservative) as Stance | null
  const neutral = safeRecord(rec.neutral) as Stance | null
  const top = safeArray<unknown>(rec.top_risks).filter(isRecord) as unknown as TopRisk[]
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">三派风险辩论</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-3">
            <StanceCard title="激进派" icon={<Flame className="h-4 w-4" />}
                         stance={aggressive} accent="aggressive" />
            <StanceCard title="保守派" icon={<Shield className="h-4 w-4" />}
                         stance={conservative} accent="conservative" />
            <StanceCard title="中立派" icon={<Scale className="h-4 w-4" />}
                         stance={neutral} accent="neutral" />
          </div>
          {nonEmptyStr(rec.verdict) && (
            <div className="rounded border-l-4 border-primary bg-primary/5 px-3 py-2 text-sm">
              <span className="font-semibold mr-2">风险综合:</span>{safeText(rec.verdict)}
            </div>
          )}
        </CardContent>
      </Card>

      {top.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">主要风险</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {top.map((r, i) => (
                <div key={i} className={`rounded border px-3 py-2 ${cellTone(r.probability, r.severity)}`}>
                  <div className="flex items-center gap-2 mb-1 text-xs">
                    <span className="font-semibold flex-1">{safeText(r.risk)}</span>
                    <span className="font-mono">概率 {PROB_LABEL[r.probability as string] ?? "—"}</span>
                    <span className="font-mono">严重 {PROB_LABEL[r.severity as string] ?? "—"}</span>
                  </div>
                  {nonEmptyStr(r.mitigation) && (
                    <div className="text-xs opacity-80">缓解: {safeText(r.mitigation)}</div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
