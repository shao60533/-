import { useEffect, useState } from "react"
import { Wallet, TrendingUp, Target, Package, Plus, Search, DollarSign, ArrowDownToLine } from "lucide-react"
import { Card, CardHeader, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { BuyDialog, SellDialog, UpdateCostDialog } from "@/components/shared/HoldingDialogs"
import { apiGet, apiDel } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Holding {
  ticker: string; market: string; shares: number; avg_cost: number
  current_price: number; market_value: number; pnl: number; pnl_pct: number
}

interface Transaction {
  id: number
  ticker: string
  // Backend canonical contract is uppercase BUY/SELL; we still accept the
  // legacy lowercase from older deploys so a client cache miss does not
  // ship a colourless row.
  action: 'BUY' | 'SELL' | 'buy' | 'sell' | string
  shares: number
  price: number
  // ``timestamp`` is canonical; ``date`` is the legacy alias kept around
  // for any pre-v1.16 payload that might still arrive from a stale cache.
  timestamp?: string
  date?: string
  notes: string
}

const isBuy = (a: string): boolean => (a || '').toUpperCase() === 'BUY'
const tsLabel = (t: Transaction): string => (t.timestamp || t.date || '')

interface Summary {
  total_value: number
  total_pnl: number
  total_pnl_pct: number
  // ``today_pnl`` is the *real* day-over-day P&L vs the prior snapshot,
  // and is ``null`` whenever there is no prior snapshot to diff against
  // (fresh DB / first day). The UI must NOT display 0 in that case —
  // it falls back to ``total_pnl`` and relabels the tile accordingly.
  today_pnl: number | null
  today_pnl_pct: number | null
  holdings_count: number
}

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }

export function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [buyOpen, setBuyOpen] = useState(false)
  const [sellTarget, setSellTarget] = useState<Holding | null>(null)
  const [costTarget, setCostTarget] = useState<Holding | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])

  const load = async () => {
    setLoading(true)
    const [h, s, t] = await Promise.all([
      apiGet<Holding[]>("/api/portfolio/holdings").catch(() => []),
      apiGet<Summary>("/api/portfolio/summary").catch(() => null),
      apiGet<Transaction[]>("/api/portfolio/transactions").catch(() => []),
    ])
    setHoldings(Array.isArray(h) ? h : [])
    setSummary(s)
    setTransactions(Array.isArray(t) ? t : [])
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const filtered = search
    ? holdings.filter(h => h.ticker.toLowerCase().includes(search.toLowerCase()))
    : holdings

  const handleRemove = async (ticker: string) => {
    if (!confirm(`确定移除 ${ticker}？`)) return
    await apiDel(`/api/portfolio/${ticker}`)
    load()
  }

  if (loading) return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
      <Skeleton className="h-8 w-40" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 grid-collapse-mobile">
        {[1,2,3,4].map(i => <Skeleton key={i} className="h-20" />)}
      </div>
      <Skeleton className="h-80" />
    </div>
  )

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6 min-w-0">
      <div className="mobile-card-header">
        <h1 className="mc-title text-xl font-bold truncate">持仓管理</h1>
        <Button size="sm" onClick={() => setBuyOpen(true)} className="mc-actions">
          <Plus className="icon-fixed mr-1" /> 买入
        </Button>
      </div>

      {/* Stats */}
      {summary && (() => {
        // When today_pnl is null (no prior snapshot), degrade to total_pnl
        // and relabel the tile rather than displaying a misleading 0.
        const showToday = summary.today_pnl != null && summary.today_pnl_pct != null
        const pnlValue = showToday ? (summary.today_pnl as number) : summary.total_pnl
        const pnlPct   = showToday ? (summary.today_pnl_pct as number) : summary.total_pnl_pct
        const pnlLabel = showToday ? "今日 PnL" : "总盈亏"
        return (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 grid-collapse-mobile">
            <Stat label="总值" value={`$${fmt(summary.total_value)}`} icon={<Wallet className="h-4 w-4" />} />
            <Stat label={pnlLabel} value={`$${fmt(pnlValue)}`} delta={pnlPct} icon={<TrendingUp className="h-4 w-4" />} />
            <Stat label="收益率" value={fmtPct(pnlPct)} icon={<Target className="h-4 w-4" />} />
            <Stat label="持仓数" value={String(summary.holdings_count)} icon={<Package className="h-4 w-4" />} />
          </div>
        )
      })()}

      {/* Holdings + Transactions tabs */}
      <Tabs defaultValue="holdings">
        <TabsList>
          <TabsTrigger value="holdings">持仓 ({holdings.length})</TabsTrigger>
          <TabsTrigger value="transactions">交易记录 ({transactions.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="holdings">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input placeholder="搜索股票..." value={search} onChange={e => setSearch(e.target.value)}
                     className="pl-9" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {holdings.length === 0 ? "暂无持仓，点击右上角「买入」添加" : "无匹配结果"}
            </div>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden md:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs uppercase">
                      <th className="text-left py-2 px-2">代码</th>
                      <th className="text-right py-2 px-2">市场</th>
                      <th className="text-right py-2 px-2">持仓</th>
                      <th className="text-right py-2 px-2">成本</th>
                      <th className="text-right py-2 px-2">现价</th>
                      <th className="text-right py-2 px-2">市值</th>
                      <th className="text-right py-2 px-2">盈亏 $</th>
                      <th className="text-right py-2 px-2">盈亏 %</th>
                      <th className="text-right py-2 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(h => (
                      <tr key={h.ticker} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2.5 px-2 font-mono font-semibold">{h.ticker}</td>
                        <td className="text-right py-2.5 px-2 text-xs text-muted-foreground">{h.market?.toUpperCase()}</td>
                        <td className="text-right py-2.5 px-2 font-mono">{h.shares}</td>
                        <td className="text-right py-2.5 px-2 font-mono cursor-pointer hover:text-primary"
                            onClick={() => setCostTarget(h)}>${fmt(h.avg_cost)}</td>
                        <td className="text-right py-2.5 px-2 font-mono">${fmt(h.current_price || 0)}</td>
                        <td className="text-right py-2.5 px-2 font-mono">${fmt(h.market_value || 0)}</td>
                        <td className={cn("text-right py-2.5 px-2 font-mono truncate",
                          (h.pnl || 0) > 0 ? "text-[var(--color-accent-green)]" : (h.pnl || 0) < 0 ? "text-[var(--color-accent-red)]" : "text-muted-foreground")}
                          style={{ fontVariantNumeric: "tabular-nums" }}>
                          {(h.pnl || 0) >= 0 ? "+" : ""}${fmt(h.pnl || 0)}
                        </td>
                        <td className={cn("text-right py-2.5 px-2 font-mono",
                          h.pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                          {fmtPct(h.pnl_pct)}
                        </td>
                        <td className="text-right py-2.5 px-2 space-x-1">
                          <Button variant="ghost" size="sm" onClick={() => setSellTarget(h)}>
                            <ArrowDownToLine className="w-3.5 h-3.5 mr-1" />卖出
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setCostTarget(h)}>
                            <DollarSign className="w-3.5 h-3.5 mr-1" />修正
                          </Button>
                          <Button variant="ghost" size="sm" className="text-[var(--color-accent-red)]" onClick={() => handleRemove(h.ticker)}>移除</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden space-y-2">
                {filtered.map(h => (
                  <div key={h.ticker} className="border rounded-lg p-3 min-w-0">
                    <div className="flex items-center justify-between gap-2 min-w-0">
                      <div className="min-w-0 flex items-center gap-1">
                        <span className="font-mono font-semibold truncate">{h.ticker}</span>
                        <span className="text-xs text-muted-foreground shrink-0">{h.shares} 股</span>
                      </div>
                      <span className={cn("font-mono text-sm shrink-0",
                        h.pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        {fmtPct(h.pnl_pct)}
                      </span>
                    </div>
                    {/* 3-stat row wraps on 320px so 成本/盈亏/现价
                        each get a full pixel column instead of being
                        squeezed into a single overflowing line. */}
                    <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 text-xs text-muted-foreground mt-1 min-w-0">
                      <span>成本 ${fmt(h.avg_cost)}</span>
                      <span className={cn("font-mono", (h.pnl || 0) >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        盈亏 {(h.pnl || 0) >= 0 ? "+" : ""}${fmt(h.pnl || 0)}
                      </span>
                      <span>现价 ${fmt(h.current_price || 0)}</span>
                    </div>
                    <div className="flex gap-2 mt-2">
                      <Button variant="outline" size="sm" className="flex-1 h-9" onClick={() => setSellTarget(h)}>卖出</Button>
                      <Button variant="outline" size="sm" className="flex-1 h-9" onClick={() => setCostTarget(h)}>修正成本</Button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

        </TabsContent>

        <TabsContent value="transactions">
          <Card>
            <CardContent className="pt-4">
              {transactions.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">暂无交易记录</div>
              ) : (
                <>
                  {/* Desktop table */}
                  <div className="hidden md:block overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-muted-foreground text-xs uppercase">
                          <th className="text-left py-2 px-2">时间</th>
                          <th className="text-left py-2 px-2">代码</th>
                          <th className="text-left py-2 px-2">操作</th>
                          <th className="text-right py-2 px-2">数量</th>
                          <th className="text-right py-2 px-2">价格</th>
                          <th className="text-left py-2 px-2">备注</th>
                        </tr>
                      </thead>
                      <tbody>
                        {transactions.map(t => (
                          <tr key={t.id} className="border-b border-border/50 hover:bg-muted/30">
                            <td className="py-2 px-2 text-xs text-muted-foreground font-mono">{tsLabel(t).slice(0, 16)}</td>
                            <td className="py-2 px-2 font-mono font-semibold">{t.ticker}</td>
                            <td className="py-2 px-2">
                              <span className={cn("text-xs font-medium", isBuy(t.action) ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                                {t.action.toUpperCase()}
                              </span>
                            </td>
                            <td className="text-right py-2 px-2 font-mono">{t.shares}</td>
                            <td className="text-right py-2 px-2 font-mono">${fmt(t.price)}</td>
                            <td className="py-2 px-2 text-xs text-muted-foreground truncate max-w-[200px]">{t.notes || "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* Mobile cards */}
                  <div className="md:hidden space-y-2">
                    {transactions.map(t => (
                      <div key={t.id} className="border rounded-lg p-3 min-w-0">
                        {/* "BUY 100 @ $123.45" can run long for 4-digit
                            share counts; flex-wrap lets it move below
                            the ticker on narrow widths. */}
                        <div className="flex flex-wrap justify-between items-baseline gap-x-2 gap-y-0.5 min-w-0">
                          <span className="font-mono font-semibold truncate min-w-0 flex-1">{t.ticker}</span>
                          <span className={cn("text-xs font-medium text-safe text-safe--wrap", isBuy(t.action) ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                            {t.action.toUpperCase()} {t.shares} @ ${fmt(t.price)}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{tsLabel(t).slice(0, 16)}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <BuyDialog open={buyOpen} onClose={() => setBuyOpen(false)} onSuccess={load} />
      <SellDialog target={sellTarget} onClose={() => setSellTarget(null)} onSuccess={load} />
      <UpdateCostDialog target={costTarget} onClose={() => setCostTarget(null)} onSuccess={load} />
    </div>
  )
}
