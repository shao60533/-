import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { Argument, DebateCardData } from "./types"

const WEIGHT_ORDER: Record<string, number> = { primary: 0, secondary: 1, tertiary: 2 }
const WEIGHT_LABEL: Record<string, string> = { primary: "核心", secondary: "次要", tertiary: "次次要" }
const WEIGHT_TONE: Record<string, string> = {
  primary:   "border-primary",
  secondary: "border-zinc-500/40",
  tertiary:  "border-zinc-700/40",
}
const VERDICT_TONE: Record<string, string> = {
  bull:  "bg-emerald-600 text-emerald-50",
  bear:  "bg-red-600 text-red-50",
  draw:  "bg-zinc-600 text-zinc-50",
}
const VERDICT_LABEL: Record<string, string> = { bull: "多方胜", bear: "空方胜", draw: "平局" }

function ArgList({ args, accent }: { args: Argument[] | undefined; accent: "bull" | "bear" }) {
  if (!args?.length) return <div className="text-xs text-muted-foreground">无论据</div>
  const sorted = [...args].sort(
    (a, b) => (WEIGHT_ORDER[a.weight ?? "secondary"] - WEIGHT_ORDER[b.weight ?? "secondary"]),
  )
  return (
    <div className="space-y-2">
      {sorted.map((a, i) => (
        <div key={i} className={`rounded border-l-4 bg-card/30 px-3 py-2 ${WEIGHT_TONE[a.weight ?? "secondary"]}`}>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant="outline" className="text-[10px]">{WEIGHT_LABEL[a.weight ?? "secondary"]}</Badge>
            <span className={`text-[10px] uppercase tracking-wider ${accent === "bull" ? "text-emerald-400" : "text-red-400"}`}>
              {accent === "bull" ? "多" : "空"}
            </span>
          </div>
          <div className="text-sm">{a.claim}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{a.evidence}</div>
        </div>
      ))}
    </div>
  )
}

export function DebateCard({ data }: { data: DebateCardData }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 flex items-center gap-3 flex-wrap">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">裁判判定</span>
          <span className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-bold ${VERDICT_TONE[data.verdict]}`}>
            {VERDICT_LABEL[data.verdict]}
          </span>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-emerald-400">看多论据</CardTitle></CardHeader>
          <CardContent><ArgList args={data.bull_arguments} accent="bull" /></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-red-400">看空论据</CardTitle></CardHeader>
          <CardContent><ArgList args={data.bear_arguments} accent="bear" /></CardContent>
        </Card>
      </div>

      {data.key_disagreement && (
        <div className="rounded border-l-4 border-amber-500/60 bg-amber-500/5 px-3 py-2 text-sm">
          <span className="font-semibold mr-2">关键分歧:</span>{data.key_disagreement}
        </div>
      )}

      {data.neutral_synthesis && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">中立综合</CardTitle></CardHeader>
          <CardContent className="text-sm leading-relaxed">{data.neutral_synthesis}</CardContent>
        </Card>
      )}
    </div>
  )
}
