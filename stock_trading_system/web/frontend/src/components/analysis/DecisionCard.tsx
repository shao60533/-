import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Check } from "lucide-react"
import type { Action, Confidence, DecisionCardData } from "./types"

const ACTION_TONE: Record<Action, string> = {
  BUY:    "bg-emerald-600 text-emerald-50",
  ADD:    "bg-emerald-500 text-emerald-50",
  SELL:   "bg-red-600 text-red-50",
  REDUCE: "bg-orange-500 text-orange-50",
  HOLD:   "bg-zinc-500 text-zinc-50",
  WAIT:   "bg-amber-500 text-amber-950",
}
const ACTION_LABEL: Record<Action, string> = {
  BUY: "买入", SELL: "卖出", HOLD: "持有",
  REDUCE: "减仓", ADD: "加仓", WAIT: "观望",
}
const CONV_TONE: Record<Confidence, string> = {
  high:   "text-emerald-400",
  medium: "text-amber-400",
  low:    "text-zinc-400",
}
const CONV_LABEL: Record<Confidence, string> = { high: "高确信", medium: "中确信", low: "低确信" }
const HORIZON_LABEL: Record<string, string> = {
  intraday: "日内", swing: "波段", short: "短期", medium: "中期", long: "长期",
}

export function DecisionCard({ data }: { data: DecisionCardData }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className={`inline-flex items-center px-4 py-1.5 rounded-md text-base font-bold ${ACTION_TONE[data.final_action]}`}>
              {ACTION_LABEL[data.final_action]}
            </span>
            <span className={`text-sm font-semibold ${CONV_TONE[data.conviction]}`}>
              {CONV_LABEL[data.conviction]}
            </span>
            <Badge variant="outline" className="text-[10px]">
              {HORIZON_LABEL[data.time_horizon] ?? data.time_horizon}
            </Badge>
          </div>
          <p className="text-sm">{data.one_line_summary}</p>
        </CardContent>
      </Card>

      {(data.entry_zone || data.structural_stop != null
         || (data.take_profit_levels && data.take_profit_levels.length > 0)) && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">价位框架</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {data.entry_zone && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20 shrink-0">入场区</span>
                <span className="font-mono">${data.entry_zone.low.toFixed(2)} – ${data.entry_zone.high.toFixed(2)}</span>
              </div>
            )}
            {data.structural_stop != null && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20 shrink-0">结构止损</span>
                <span className="font-mono text-red-400">${data.structural_stop.toFixed(2)}</span>
              </div>
            )}
            {data.take_profit_levels && data.take_profit_levels.length > 0 && (
              <div>
                <div className="text-xs text-muted-foreground mb-1">止盈分档</div>
                <div className="space-y-1">
                  {data.take_profit_levels.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono w-20">${t.price.toFixed(2)}</span>
                      <span className="font-mono text-emerald-400 w-12">{t.weight_pct}%</span>
                      {t.rationale && <span className="text-muted-foreground">{t.rationale}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {((data.preconditions && data.preconditions.length > 0)
        || (data.exit_conditions && data.exit_conditions.length > 0)) && (
        <div className="grid gap-3 md:grid-cols-2">
          {data.preconditions && data.preconditions.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">前置条件</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">
                  {data.preconditions.map((p, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <Check className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
          {data.exit_conditions && data.exit_conditions.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">退出条件</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">
                  {data.exit_conditions.map((e, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <Check className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
                      <span>{e}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {data.alternative_scenarios && data.alternative_scenarios.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">备选场景</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr><th className="text-left py-1 pr-3">条件</th><th className="text-left py-1">动作</th></tr>
              </thead>
              <tbody>
                {data.alternative_scenarios.map((s, i) => (
                  <tr key={i} className="border-t border-border/30">
                    <td className="py-1.5 pr-3">{s.condition}</td>
                    <td className="py-1.5 font-semibold">{s.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
