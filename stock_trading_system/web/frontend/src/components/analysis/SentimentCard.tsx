import { AlertTriangle } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { SentimentCardData } from "./types"
import { MoodGauge } from "./shared/MoodGauge"

const POLARITY_TONE: Record<string, string> = {
  bullish: "border-emerald-500/40 text-emerald-400",
  bearish: "border-red-500/40 text-red-400",
  mixed:   "border-amber-500/40 text-amber-300",
}
const SOURCE_LABEL: Record<string, string> = {
  news: "新闻", social: "社交", options: "期权",
  analyst: "分析师", insider: "内部",
}

export function SentimentCard({ data }: { data: SentimentCardData }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 flex items-center gap-4 flex-wrap">
          <MoodGauge mood={data.mood} score={data.mood_score} />
          {data.summary && (
            <p className="text-sm leading-relaxed flex-1 min-w-[240px]">{data.summary}</p>
          )}
        </CardContent>
      </Card>

      {data.contrarian_signal && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="pt-3 flex items-start gap-2 text-sm">
            <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold text-amber-300">逆向信号</div>
              {data.contrarian_reason && (
                <div className="text-xs text-muted-foreground mt-0.5">{data.contrarian_reason}</div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {data.drivers && data.drivers.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">驱动因子</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {data.drivers.map((d, i) => (
              <div key={i} className={`flex items-start gap-3 rounded border bg-card/30 px-3 py-2 ${POLARITY_TONE[d.polarity] ?? "border-zinc-500/30"}`}>
                <Badge variant="outline" className="text-[10px]">{SOURCE_LABEL[d.source] ?? d.source}</Badge>
                <span className="text-sm flex-1">{d.theme}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
