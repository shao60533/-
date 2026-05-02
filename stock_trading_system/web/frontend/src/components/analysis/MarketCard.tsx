import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type {
  MarketCardData, Trend, TechnicalIndicator, PriceLevel,
} from "./types"
import {
  safeArray, fmtNumber, nonEmptyStr, toFiniteNumber, safeText,
  safeRecord, isRecord,
} from "./shared/defensive"

const TREND_TONE: Record<string, string> = {
  bullish: "bg-emerald-600/20 text-emerald-400 border-emerald-500/40",
  bearish: "bg-red-600/20 text-red-400 border-red-500/40",
  neutral: "bg-zinc-600/20 text-zinc-300 border-zinc-500/30",
  range:   "bg-amber-600/20 text-amber-300 border-amber-500/40",
}
const TREND_LABEL: Record<string, string> = {
  bullish: "看涨", bearish: "看跌", neutral: "中性", range: "震荡",
}

function safeTrend(t: unknown): Trend {
  return typeof t === "string" && t in TREND_LABEL ? (t as Trend) : "neutral"
}

const SIGNAL_DOT: Record<string, string> = {
  bullish: "bg-emerald-500",
  bearish: "bg-red-500",
  neutral: "bg-zinc-500",
}

const KIND_LABEL: Record<string, string> = {
  support: "支撑", resistance: "阻力", pivot: "枢轴",
}
const STRENGTH_TONE: Record<string, string> = {
  strong: "border-primary",
  medium: "border-zinc-500/40",
  weak:   "border-zinc-700/40",
}

export function MarketCard({ data }: { data: MarketCardData | null | undefined }) {
  const rec = safeRecord(data)
  if (!rec) return null
  const trend = safeTrend(rec.trend)
  // Items must be records before we read ``it.signal`` / ``it.value`` —
  // a string/null item slipping through would still not throw thanks
  // to ``safeText``, but ``signal`` lookup would silently misclassify.
  const indicators = safeArray<unknown>(rec.indicators)
    .filter(isRecord) as unknown as TechnicalIndicator[]
  // ``support_resistance``: drop entries whose price isn't a real number
  // before sorting — the production payload had ``price: "—"`` for two
  // levels, which crashed the descending sort with NaN comparisons.
  const levels = safeArray<unknown>(rec.support_resistance)
    .filter(isRecord)
    .map(p => ({ ...(p as unknown as PriceLevel), _num: toFiniteNumber((p as Record<string, unknown>).price) }))
    .filter(p => p._num !== null) as Array<PriceLevel & { _num: number }>
  levels.sort((a, b) => b._num - a._num)
  const patterns = safeArray<unknown>(rec.patterns)
    .filter((p): p is string => nonEmptyStr(p))
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">趋势</span>
            <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold ${TREND_TONE[trend]}`}>
              {TREND_LABEL[trend]}
            </span>
          </div>
          {nonEmptyStr(rec.summary) && (
            <p className="text-sm leading-relaxed">{safeText(rec.summary)}</p>
          )}
        </CardContent>
      </Card>

      {indicators.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">技术指标</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {indicators.map((it, i) => (
                <div key={i} className="rounded border border-border/40 bg-card/40 p-2">
                  <div className="flex items-center gap-1.5">
                    <span className={`inline-block w-2 h-2 rounded-full ${SIGNAL_DOT[it.signal as string] ?? "bg-zinc-500"}`} />
                    <span className="text-xs text-muted-foreground">{safeText(it.name)}</span>
                  </div>
                  <div className="font-mono text-sm mt-0.5">
                    {safeText(it.value, "—")}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {levels.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">关键价位</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {levels.map((p, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-3 rounded border-l-4 ${STRENGTH_TONE[p.strength ?? "medium"] ?? STRENGTH_TONE.medium} px-3 py-1.5 bg-card/30`}
                >
                  <span className="font-mono text-sm">${fmtNumber(p._num, 2)}</span>
                  <Badge variant="muted" className="text-[10px]">
                    {KIND_LABEL[p.kind ?? ""] ?? safeText(p.kind, "—")}
                  </Badge>
                  {nonEmptyStr(p.note) && (
                    <span className="text-xs text-muted-foreground">{safeText(p.note)}</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {patterns.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">形态</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {patterns.map((p, i) => (
                <Badge key={i} variant="outline">{safeText(p)}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
