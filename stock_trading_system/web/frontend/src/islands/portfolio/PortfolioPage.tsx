import { useEffect, useState } from "react"
import { Wallet, TrendingUp, Target, Package, Plus, Search } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { apiGet, apiPost, apiDel } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Holding {
  ticker: string; market: string; shares: number; avg_cost: number
  current_price: number; market_value: number; pnl: number; pnl_pct: number
}

interface Summary {
  total_value: number; today_pnl: number; today_pnl_pct: number; holdings_count: number
}

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }

export function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [buyOpen, setBuyOpen] = useState(false)

  const load = async () => {
    setLoading(true)
    const [h, s] = await Promise.all([
      apiGet<Holding[]>("/api/portfolio/holdings").catch(() => []),
      apiGet<Summary>("/api/portfolio/summary").catch(() => null),
    ])
    setHoldings(Array.isArray(h) ? h : [])
    setSummary(s)
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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-20" />)}</div>
      <Skeleton className="h-80" />
    </div>
  )

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">持仓管理</h1>
        <Button size="sm" onClick={() => setBuyOpen(true)}>
          <Plus className="w-4 h-4 mr-1" /> 买入
        </Button>
      </div>

      {/* Stats */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="总值" value={`$${fmt(summary.total_value)}`} icon={<Wallet className="h-4 w-4" />} />
          <Stat label="今日 PnL" value={`$${fmt(summary.today_pnl)}`} delta={summary.today_pnl_pct} icon={<TrendingUp className="h-4 w-4" />} />
          <Stat label="收益率" value={fmtPct(summary.today_pnl_pct)} icon={<Target className="h-4 w-4" />} />
          <Stat label="持仓数" value={String(summary.holdings_count)} icon={<Package className="h-4 w-4" />} />
        </div>
      )}

      {/* Holdings table */}
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
                      <th className="text-right py-2 px-2">持仓</th>
                      <th className="text-right py-2 px-2">成本</th>
                      <th className="text-right py-2 px-2">现价</th>
                      <th className="text-right py-2 px-2">盈亏</th>
                      <th className="text-right py-2 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(h => (
                      <tr key={h.ticker} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2.5 px-2 font-mono font-semibold">{h.ticker}
                          <span className="text-xs text-muted-foreground ml-1">{h.market?.toUpperCase()}</span>
                        </td>
                        <td className="text-right py-2.5 px-2 font-mono">{h.shares}</td>
                        <td className="text-right py-2.5 px-2 font-mono">${fmt(h.avg_cost)}</td>
                        <td className="text-right py-2.5 px-2 font-mono">${fmt(h.current_price || 0)}</td>
                        <td className={cn("text-right py-2.5 px-2 font-mono",
                          h.pnl_pct >= 0 ? "text-green-500" : "text-red-500")}>
                          {fmtPct(h.pnl_pct)}
                        </td>
                        <td className="text-right py-2.5 px-2">
                          <Button variant="ghost" size="sm" onClick={() => window.location.href = `/app#analysis`}>分析</Button>
                          <Button variant="ghost" size="sm" className="text-red-500" onClick={() => handleRemove(h.ticker)}>移除</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden space-y-2">
                {filtered.map(h => (
                  <div key={h.ticker} className="border rounded-lg p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-mono font-semibold">{h.ticker}</span>
                        <span className="text-xs text-muted-foreground ml-1">{h.shares} 股</span>
                      </div>
                      <span className={cn("font-mono text-sm",
                        h.pnl_pct >= 0 ? "text-green-500" : "text-red-500")}>
                        {fmtPct(h.pnl_pct)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>成本 ${fmt(h.avg_cost)}</span>
                      <span>现价 ${fmt(h.current_price || 0)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Buy Dialog */}
      <BuyDialog open={buyOpen} onClose={() => setBuyOpen(false)} onSuccess={load} />
    </div>
  )
}

function BuyDialog({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [ticker, setTicker] = useState("")
  const [shares, setShares] = useState("")
  const [price, setPrice] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!ticker || !shares || !price) return
    setSubmitting(true)
    try {
      await apiPost("/api/portfolio/add", { ticker, shares: parseFloat(shares), price: parseFloat(price) })
      onSuccess()
      onClose()
      setTicker(""); setShares(""); setPrice("")
    } catch (e: any) {
      alert(e.message || "买入失败")
    }
    setSubmitting(false)
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader><DialogTitle>买入股票</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <Input placeholder="股票代码 (如 AAPL)" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} />
          <Input type="number" placeholder="数量" value={shares} onChange={e => setShares(e.target.value)} />
          <Input type="number" placeholder="价格" step="0.01" value={price} onChange={e => setPrice(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "提交中..." : "买入"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
