import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { NewsCardData, Headline, Catalyst } from "./types"
import { safeArray, nonEmptyStr, safeText, isRecord, safeRecord } from "./shared/defensive"

const SENTIMENT_DOT: Record<string, string> = {
  bullish: "bg-emerald-500",
  bearish: "bg-red-500",
  neutral: "bg-zinc-500",
}
const IMPACT_BAR: Record<string, string> = {
  high:   "h-3 bg-primary",
  medium: "h-2 bg-zinc-400/60",
  low:    "h-1 bg-zinc-500/40",
}
const KIND_LABEL: Record<string, string> = {
  earnings: "财报", macro: "宏观", sector: "行业",
  company: "公司", regulatory: "监管",
}

export function NewsCard({ data }: { data: NewsCardData | null | undefined }) {
  const rec = safeRecord(data)
  if (!rec) return null
  const headlines = safeArray<unknown>(rec.headlines).filter(isRecord) as unknown as Headline[]
  const catalysts = safeArray<unknown>(rec.catalysts).filter(isRecord) as unknown as Catalyst[]
  return (
    <div className="space-y-4">
      {nonEmptyStr(rec.summary) && (
        <Card>
          <CardContent className="pt-4 text-sm leading-relaxed">{safeText(rec.summary)}</CardContent>
        </Card>
      )}

      {headlines.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">头条</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {headlines.map((h, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="flex flex-col items-center gap-1 mt-1">
                    <span className={`inline-block w-2 h-2 rounded-full ${SENTIMENT_DOT[h.sentiment ?? "neutral"] ?? SENTIMENT_DOT.neutral}`} />
                    <span className={`block w-1 rounded ${IMPACT_BAR[h.impact ?? "medium"] ?? IMPACT_BAR.medium}`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-sm">{safeText(h.title)}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5 flex gap-2">
                      {nonEmptyStr(h.source) && <span>{safeText(h.source)}</span>}
                      {nonEmptyStr(h.date) && <span>· {safeText(h.date)}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {catalysts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">催化剂时间线</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {catalysts.map((c, i) => (
                <div key={i} className="flex items-start gap-3 rounded border border-border/40 bg-card/30 px-3 py-2">
                  <Badge variant="outline" className="text-[10px]">
                    {KIND_LABEL[c.kind as string] ?? safeText(c.kind, "—")}
                  </Badge>
                  <div className="flex-1 text-sm">
                    {safeText(c.summary)}
                    {nonEmptyStr(c.date) && (
                      <div className="text-[10px] text-muted-foreground mt-0.5">{safeText(c.date)}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
