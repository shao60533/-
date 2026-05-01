import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { NewsCardData } from "./types"

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

export function NewsCard({ data }: { data: NewsCardData }) {
  return (
    <div className="space-y-4">
      {data.summary && (
        <Card>
          <CardContent className="pt-4 text-sm leading-relaxed">{data.summary}</CardContent>
        </Card>
      )}

      {data.headlines && data.headlines.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">头条</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.headlines.map((h, i) => (
                <div key={i} className="flex items-start gap-3">
                  <div className="flex flex-col items-center gap-1 mt-1">
                    <span className={`inline-block w-2 h-2 rounded-full ${SENTIMENT_DOT[h.sentiment ?? "neutral"]}`} />
                    <span className={`block w-1 rounded ${IMPACT_BAR[h.impact ?? "medium"]}`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-sm">{h.title}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5 flex gap-2">
                      {h.source && <span>{h.source}</span>}
                      {h.date && <span>· {h.date}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {data.catalysts && data.catalysts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">催化剂时间线</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.catalysts.map((c, i) => (
                <div key={i} className="flex items-start gap-3 rounded border border-border/40 bg-card/30 px-3 py-2">
                  <Badge variant="outline" className="text-[10px]">{KIND_LABEL[c.kind] ?? c.kind}</Badge>
                  <div className="flex-1 text-sm">
                    {c.summary}
                    {c.date && (
                      <div className="text-[10px] text-muted-foreground mt-0.5">{c.date}</div>
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
