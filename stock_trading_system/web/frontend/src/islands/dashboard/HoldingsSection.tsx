import { useMemo, useState } from "react"
import { Plus, Search, Sparkles } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Chip, ChipRow } from "@/components/ui/chip"
import {
  BuyDialog, SellDialog, UpdateCostDialog,
  type HoldingTarget,
} from "@/components/shared/HoldingDialogs"
import { apiDel } from "@/lib/api"
import { cn } from "@/lib/utils"

// Default visible count per mobile-ui-v1.3 §4.2 — show 5 cards by
// default, full list (typically 9) when the user clicks 全部 N.
const DEFAULT_VISIBLE = 5

export interface DashboardHolding {
  ticker: string
  market: string
  shares: number
  avg_cost: number
  current_price: number
  market_value: number
  pnl: number
  pnl_pct: number
}

function fmt(n: number) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtPct(n: number) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`
}

export function HoldingsSection({
  holdings,
  transactionsCount,
  onChange,
}: {
  holdings: DashboardHolding[]
  transactionsCount: number
  onChange: () => void
}) {
  const [search, setSearch] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [buyOpen, setBuyOpen] = useState(false)
  const [sellTarget, setSellTarget] = useState<HoldingTarget | null>(null)
  const [costTarget, setCostTarget] = useState<HoldingTarget | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return holdings
    return holdings.filter(h => h.ticker.toLowerCase().includes(q))
  }, [holdings, search])

  const visible = showAll ? filtered : filtered.slice(0, DEFAULT_VISIBLE)
  const total = holdings.length

  const handleRemove = async (ticker: string) => {
    if (!confirm(`确定移除 ${ticker}？`)) return
    await apiDel(`/api/portfolio/${ticker}`)
    onChange()
  }

  return (
    <section className="space-y-3" data-section="holdings">
      <div className="flex items-baseline justify-between gap-2 min-w-0">
        <h2 className="text-base font-semibold truncate">持仓明细</h2>
        <span className="text-xs text-muted-foreground shrink-0">{total} 只股票</span>
      </div>

      {/* Toolbar — search + buy entry, then chips for visibility +
          shortcuts to transactions and paper-trade. */}
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center gap-2 min-w-0">
            <div className="relative flex-1 min-w-0">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索股票..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Button size="sm" onClick={() => setBuyOpen(true)} className="shrink-0">
              <Plus className="w-4 h-4 mr-1" /> 买入
            </Button>
          </div>
          <ChipRow>
            <Chip active={!showAll} onClick={() => setShowAll(false)} data-holdings-toggle="five">
              显示 {Math.min(DEFAULT_VISIBLE, total) || DEFAULT_VISIBLE}
            </Chip>
            <Chip active={showAll} onClick={() => setShowAll(true)} data-holdings-toggle="all">
              全部 {total}
            </Chip>
            <Chip onClick={() => (window.location.href = "/portfolio")}>
              交易记录 {transactionsCount}
            </Chip>
            <Chip onClick={() => (window.location.href = "/paper-trade")}>
              纸面计划
            </Chip>
          </ChipRow>
        </CardContent>
      </Card>

      {/* Product gap note: batch_analysis worker exists but no real
          mobile entry yet. Don't pretend it's implemented. */}
      <Card className="border-dashed border-[var(--color-accent-yellow)]/40 bg-[var(--color-accent-yellow)]/5">
        <CardContent className="pt-4 space-y-2">
          <div className="flex items-center justify-between gap-2 min-w-0">
            <strong className="text-sm truncate">建议补齐入口：批量分析持仓</strong>
            <Badge variant="outline" className="shrink-0 text-[10px]">产品缺口</Badge>
          </div>
          <p className="text-xs text-muted-foreground break-words">
            后端 batch_analysis worker 与任务类型已存在，但真实前端暂无触发按钮。合并后应放在首页持仓明细上方，作为批量复核的主入口。
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => alert("产品缺口：批量分析持仓尚未接入前端入口")}
            >
              批量分析持仓
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => (window.location.href = "/tasks")}
            >
              查看任务类型
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Holding cards — default to first 5; "全部 N" reveals the rest.
          Each card carries 看分析 + 卖出 / 修正成本 / 移除. */}
      {filtered.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            {holdings.length === 0 ? "暂无持仓，点击右上角「买入」添加" : "无匹配结果"}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2" data-holdings-list>
          {visible.map(h => (
            <HoldingCard
              key={h.ticker}
              h={h}
              onAnalyze={() => {
                window.location.href = `/analysis?ticker=${encodeURIComponent(h.ticker)}`
              }}
              onSell={() => setSellTarget({
                ticker: h.ticker, shares: h.shares,
                avg_cost: h.avg_cost, current_price: h.current_price,
              })}
              onCost={() => setCostTarget({
                ticker: h.ticker, shares: h.shares,
                avg_cost: h.avg_cost, current_price: h.current_price,
              })}
              onRemove={() => handleRemove(h.ticker)}
            />
          ))}
        </div>
      )}

      <BuyDialog open={buyOpen} onClose={() => setBuyOpen(false)} onSuccess={onChange} />
      <SellDialog target={sellTarget} onClose={() => setSellTarget(null)} onSuccess={onChange} />
      <UpdateCostDialog target={costTarget} onClose={() => setCostTarget(null)} onSuccess={onChange} />
    </section>
  )
}

function HoldingCard({
  h, onAnalyze, onSell, onCost, onRemove,
}: {
  h: DashboardHolding
  onAnalyze: () => void
  onSell: () => void
  onCost: () => void
  onRemove: () => void
}) {
  const pnlAbs = h.pnl ?? 0
  const pnlClass = pnlAbs > 0
    ? "text-[var(--color-accent-green)]"
    : pnlAbs < 0
      ? "text-[var(--color-accent-red)]"
      : "text-muted-foreground"
  const pctClass = h.pnl_pct >= 0
    ? "text-[var(--color-accent-green)]"
    : "text-[var(--color-accent-red)]"

  return (
    <article className="rounded-lg border border-border p-3 space-y-2 min-w-0" data-holding-ticker={h.ticker}>
      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="min-w-0">
          <div className="font-mono font-semibold truncate">{h.ticker}</div>
          <div className="text-xs text-muted-foreground truncate">
            {h.shares} 股 · {h.market?.toUpperCase() || "—"}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("font-mono text-sm tabular-nums", pctClass)}>
            {fmtPct(h.pnl_pct)}
          </span>
          <Button size="sm" variant="ghost" onClick={onAnalyze}
                  className="h-8 px-2 text-xs">
            <Sparkles className="w-3.5 h-3.5 mr-1" /> 看分析
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-x-3 gap-y-1 text-xs min-w-0">
        <div className="min-w-0">
          <span className="text-muted-foreground">成本</span>
          <div className="font-mono truncate">${fmt(h.avg_cost || 0)}</div>
        </div>
        <div className="min-w-0">
          <span className="text-muted-foreground">现价</span>
          <div className="font-mono truncate">${fmt(h.current_price || 0)}</div>
        </div>
        <div className="min-w-0">
          <span className="text-muted-foreground">盈亏</span>
          <div className={cn("font-mono truncate tabular-nums", pnlClass)}>
            {pnlAbs >= 0 ? "+" : ""}${fmt(pnlAbs)}
          </div>
        </div>
        <div className="min-w-0">
          <span className="text-muted-foreground">市值</span>
          <div className="font-mono truncate">${fmt(h.market_value || 0)}</div>
        </div>
        <div className="min-w-0 col-span-2">
          <span className="text-muted-foreground">仓位 / 状态</span>
          <div className="truncate">持有</div>
        </div>
      </div>

      <div className="flex gap-2 pt-1">
        <Button variant="outline" size="sm" className="flex-1 h-9" onClick={onSell}>
          卖出
        </Button>
        <Button variant="outline" size="sm" className="flex-1 h-9" onClick={onCost}>
          修正成本
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1 h-9 text-[var(--color-accent-red)]"
          onClick={onRemove}
        >
          移除
        </Button>
      </div>
    </article>
  )
}
