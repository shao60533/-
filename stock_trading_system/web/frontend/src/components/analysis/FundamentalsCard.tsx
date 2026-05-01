import { Star } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import type { FundamentalsCardData } from "./types"

interface CellSpec { label: string; value: number | null | undefined; unit?: string }

function fmt(v: number | null | undefined, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const rounded = Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)
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

export function FundamentalsCard({ data }: { data: FundamentalsCardData }) {
  const v = data.valuation || {}
  const g = data.growth || {}
  const p = data.profitability || {}
  const b = data.balance_sheet || {}
  const score = Math.max(1, Math.min(5, data.quality_score ?? 3))
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
          {data.summary && <p className="text-sm flex-1 min-w-[200px]">{data.summary}</p>}
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

      {v.vs_industry && (
        <div className="text-xs text-muted-foreground">
          <span className="font-semibold mr-1">行业对比:</span>{v.vs_industry}
        </div>
      )}
    </div>
  )
}
