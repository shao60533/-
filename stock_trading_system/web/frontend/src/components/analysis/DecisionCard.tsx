import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Check } from "lucide-react"
import type {
  Action, Confidence, DecisionCardData,
  TakeProfitLevel, AlternativeScenario,
} from "./types"
import {
  safeArray, fmtNumber, toFiniteNumber, nonEmptyStr,
} from "./shared/defensive"

const ACTION_TONE: Record<string, string> = {
  BUY:    "bg-emerald-600 text-emerald-50",
  ADD:    "bg-emerald-500 text-emerald-50",
  SELL:   "bg-red-600 text-red-50",
  REDUCE: "bg-orange-500 text-orange-50",
  HOLD:   "bg-zinc-500 text-zinc-50",
  WAIT:   "bg-amber-500 text-amber-950",
}
const ACTION_LABEL: Record<string, string> = {
  BUY: "买入", SELL: "卖出", HOLD: "持有",
  REDUCE: "减仓", ADD: "加仓", WAIT: "观望",
}
const CONV_TONE: Record<string, string> = {
  high:   "text-emerald-400",
  medium: "text-amber-400",
  low:    "text-zinc-400",
}
const CONV_LABEL: Record<string, string> = { high: "高确信", medium: "中确信", low: "低确信" }
const HORIZON_LABEL: Record<string, string> = {
  intraday: "日内", swing: "波段", short: "短期", medium: "中期", long: "长期",
}

function safeAction(a: unknown): Action {
  return typeof a === "string" && a in ACTION_LABEL ? (a as Action) : "HOLD"
}
function safeConfidence(c: unknown): Confidence {
  return typeof c === "string" && c in CONV_LABEL ? (c as Confidence) : "medium"
}

export function DecisionCard({ data }: { data: DecisionCardData | null | undefined }) {
  if (!data || typeof data !== "object") return null

  const action = safeAction(data.final_action)
  const conv = safeConfidence(data.conviction)
  const horizon = typeof data.time_horizon === "string" ? data.time_horizon : ""

  // entry_zone may be missing fields, scalars instead of objects, or
  // strings ("$150"). Validate both ends as finite numbers.
  const ezLow = toFiniteNumber(data.entry_zone?.low)
  const ezHigh = toFiniteNumber(data.entry_zone?.high)
  const hasEntryZone = ezLow !== null && ezHigh !== null
  const stop = toFiniteNumber(data.structural_stop)
  const tp = safeArray<TakeProfitLevel>(data.take_profit_levels)
    .map(t => ({
      ...t,
      _price: toFiniteNumber(t?.price),
      _weight: toFiniteNumber(t?.weight_pct),
    }))
    .filter(t => t._price !== null) as Array<TakeProfitLevel & { _price: number; _weight: number | null }>
  const preconditions = safeArray<string>(data.preconditions).filter(nonEmptyStr)
  const exitConditions = safeArray<string>(data.exit_conditions).filter(nonEmptyStr)
  const alts = safeArray<AlternativeScenario>(data.alternative_scenarios)

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className={`inline-flex items-center px-4 py-1.5 rounded-md text-base font-bold ${ACTION_TONE[action]}`}>
              {ACTION_LABEL[action]}
            </span>
            <span className={`text-sm font-semibold ${CONV_TONE[conv]}`}>
              {CONV_LABEL[conv]}
            </span>
            <Badge variant="outline" className="text-[10px]">
              {HORIZON_LABEL[horizon] ?? (horizon || "—")}
            </Badge>
          </div>
          {nonEmptyStr(data.one_line_summary) && (
            <p className="text-sm">{data.one_line_summary}</p>
          )}
        </CardContent>
      </Card>

      {(hasEntryZone || stop !== null || tp.length > 0) && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">价位框架</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {hasEntryZone && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20 shrink-0">入场区</span>
                <span className="font-mono">${fmtNumber(ezLow, 2)} – ${fmtNumber(ezHigh, 2)}</span>
              </div>
            )}
            {stop !== null && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20 shrink-0">结构止损</span>
                <span className="font-mono text-red-400">${fmtNumber(stop, 2)}</span>
              </div>
            )}
            {tp.length > 0 && (
              <div>
                <div className="text-xs text-muted-foreground mb-1">止盈分档</div>
                <div className="space-y-1">
                  {tp.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono w-20">${fmtNumber(t._price, 2)}</span>
                      <span className="font-mono text-emerald-400 w-12">
                        {t._weight !== null ? `${t._weight}%` : "—"}
                      </span>
                      {nonEmptyStr(t.rationale) && (
                        <span className="text-muted-foreground">{t.rationale}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {(preconditions.length > 0 || exitConditions.length > 0) && (
        <div className="grid gap-3 md:grid-cols-2">
          {preconditions.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">前置条件</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">
                  {preconditions.map((p, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <Check className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
          {exitConditions.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">退出条件</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-1 text-sm">
                  {exitConditions.map((e, i) => (
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

      {alts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">备选场景</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr><th className="text-left py-1 pr-3">条件</th><th className="text-left py-1">动作</th></tr>
              </thead>
              <tbody>
                {alts.map((s, i) => (
                  <tr key={i} className="border-t border-border/30">
                    <td className="py-1.5 pr-3">{s?.condition ?? ""}</td>
                    <td className="py-1.5 font-semibold">{s?.action ?? ""}</td>
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
