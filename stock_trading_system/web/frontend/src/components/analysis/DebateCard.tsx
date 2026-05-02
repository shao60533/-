import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { Argument, DebateCardData } from "./types"
import { safeArray, nonEmptyStr, safeText, isRecord, safeRecord } from "./shared/defensive"

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

function ArgList({ args, accent }: { args: unknown; accent: "bull" | "bear" }) {
  const list = safeArray<unknown>(args).filter(isRecord) as unknown as Argument[]
  if (list.length === 0) return <div className="text-xs text-muted-foreground">无论据</div>
  const sorted = [...list].sort((a, b) => {
    const aw = WEIGHT_ORDER[a.weight ?? "secondary"] ?? 1
    const bw = WEIGHT_ORDER[b.weight ?? "secondary"] ?? 1
    return aw - bw
  })
  return (
    <div className="space-y-2">
      {sorted.map((a, i) => {
        const w = a.weight ?? "secondary"
        const tone = WEIGHT_TONE[w] ?? WEIGHT_TONE.secondary
        return (
          <div key={i} className={`rounded border-l-4 bg-card/30 px-3 py-2 ${tone}`}>
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="outline" className="text-[10px]">{WEIGHT_LABEL[w] ?? safeText(w, "次要")}</Badge>
              <span className={`text-[10px] uppercase tracking-wider ${accent === "bull" ? "text-emerald-400" : "text-red-400"}`}>
                {accent === "bull" ? "多" : "空"}
              </span>
            </div>
            {nonEmptyStr(a.claim) && <div className="text-sm">{safeText(a.claim)}</div>}
            {nonEmptyStr(a.evidence) && (
              <div className="text-xs text-muted-foreground mt-0.5">{safeText(a.evidence)}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function DebateCard({ data }: { data: DebateCardData | null | undefined }) {
  const rec = safeRecord(data)
  if (!rec) return null
  const verdict = typeof rec.verdict === "string" && rec.verdict in VERDICT_LABEL
    ? rec.verdict : "draw"
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 flex items-center gap-3 flex-wrap">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">裁判判定</span>
          <span className={`inline-flex items-center px-2.5 py-1 rounded text-xs font-bold ${VERDICT_TONE[verdict]}`}>
            {VERDICT_LABEL[verdict]}
          </span>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-emerald-400">看多论据</CardTitle></CardHeader>
          <CardContent><ArgList args={rec.bull_arguments} accent="bull" /></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-red-400">看空论据</CardTitle></CardHeader>
          <CardContent><ArgList args={rec.bear_arguments} accent="bear" /></CardContent>
        </Card>
      </div>

      {nonEmptyStr(rec.key_disagreement) && (
        <div className="rounded border-l-4 border-amber-500/60 bg-amber-500/5 px-3 py-2 text-sm">
          <span className="font-semibold mr-2">关键分歧:</span>{safeText(rec.key_disagreement)}
        </div>
      )}

      {nonEmptyStr(rec.neutral_synthesis) && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">中立综合</CardTitle></CardHeader>
          <CardContent className="text-sm leading-relaxed">{safeText(rec.neutral_synthesis)}</CardContent>
        </Card>
      )}
    </div>
  )
}
