import { Star } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { FundamentalsCardData } from "./types"
import { toFiniteNumber, nonEmptyStr, safeText, safeRecord } from "./shared/defensive"

interface CellSpec { label: string; value: unknown; unit?: string }

function fmt(v: unknown, unit = ""): string {
  const n = toFiniteNumber(v)
  if (n === null) return "—"
  const rounded = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2)
  return unit ? `${rounded}${unit}` : rounded
}

function MetricBlock({ title, items }: { title: string; items: CellSpec[] }) {
  return (
    <div className="rounded border border-border/40 bg-card/30 p-3 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{title}</div>
      <div className="grid grid-cols-2 gap-1">
        {items.map((it, i) => (
          <div key={i}>
            <div className="text-[10px] text-muted-foreground">{it.label}</div>
            <div className="font-mono text-sm">{fmt(it.value, it.unit)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function FundamentalsCard({ data }: { data: FundamentalsCardData | null | undefined }) {
  const rec = safeRecord(data)
  if (!rec) return null
  const v = (safeRecord(rec.valuation) ?? {}) as Record<string, unknown>
  const g = (safeRecord(rec.growth) ?? {}) as Record<string, unknown>
  const p = (safeRecord(rec.profitability) ?? {}) as Record<string, unknown>
  const b = (safeRecord(rec.balance_sheet) ?? {}) as Record<string, unknown>
  const qsRaw = toFiniteNumber(rec.quality_score)
  const score = qsRaw === null ? 3 : Math.max(1, Math.min(5, Math.round(qsRaw)))
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4 flex items-center gap-3 flex-wrap">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">质量评分</span>
          <div className="flex items-center gap-0.5">
            {[1, 2, 3, 4, 5].map(i => (
              <Star key={i}
                    className={`h-4 w-4 ${i <= score ? "fill-amber-400 text-amber-400" : "text-zinc-600"}`} />
            ))}
          </div>
          {nonEmptyStr(rec.summary) && <p className="text-sm flex-1 min-w-[200px]">{safeText(rec.summary)}</p>}
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <MetricBlock title="估值" items={[
          { label: "PE", value: v.pe },
          { label: "PB", value: v.pb },
          { label: "PS", value: v.ps },
          { label: "EV/EBITDA", value: v.ev_ebitda },
          { label: "PEG", value: v.peg },
        ]} />
        <MetricBlock title="增长 (YoY)" items={[
          { label: "营收", value: g.revenue_yoy_pct, unit: "%" },
          { label: "EPS", value: g.eps_yoy_pct, unit: "%" },
          { label: "FCF", value: g.fcf_yoy_pct, unit: "%" },
        ]} />
        <MetricBlock title="盈利能力" items={[
          { label: "毛利率", value: p.gross_margin_pct, unit: "%" },
          { label: "运营利润率", value: p.op_margin_pct, unit: "%" },
          { label: "ROE", value: p.roe_pct, unit: "%" },
          { label: "ROIC", value: p.roic_pct, unit: "%" },
        ]} />
        <MetricBlock title="资产负债" items={[
          { label: "资产负债率", value: b.debt_to_equity },
          { label: "流动比率", value: b.current_ratio },
          { label: "现金比率", value: b.cash_ratio },
        ]} />
      </div>

      {nonEmptyStr(v.vs_industry) && (
        <div className="text-xs text-muted-foreground">
          <span className="font-semibold mr-1">行业对比:</span>{safeText(v.vs_industry)}
        </div>
      )}
    </div>
  )
}
