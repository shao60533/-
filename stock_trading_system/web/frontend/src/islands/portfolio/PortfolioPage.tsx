import { useEffect, useState } from "react"
import { Wallet, TrendingUp, Target, Package, Plus, Search, DollarSign, ArrowDownToLine } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { apiGet, apiPost, apiDel } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Holding {
  ticker: string; market: string; shares: number; avg_cost: number
  current_price: number; market_value: number; pnl: number; pnl_pct: number
}

interface Transaction {
  id: number; ticker: string; action: string; shares: number
  price: number; timestamp: string; notes: string
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
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">持仓管理</h1>
        <Button size="sm" onClick={() => setBuyOpen(true)}>
          <Plus className="w-4 h-4 mr-1" /> 买入
        </Button>
      </div>

      {/* Stats */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4 grid-collapse-mobile">
          <Stat label="总值" value={`$${fmt(summary.total_value)}`} icon={<Wallet className="h-4 w-4" />} />
          <Stat label="今日 PnL" value={`$${fmt(summary.today_pnl)}`} delta={summary.today_pnl_pct} icon={<TrendingUp className="h-4 w-4" />} />
          <Stat label="收益率" value={fmtPct(summary.today_pnl_pct)} icon={<Target className="h-4 w-4" />} />
          <Stat label="持仓数" value={String(summary.holdings_count)} icon={<Package className="h-4 w-4" />} />
        </div>
      )}

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
                      <th className="text-right py-2 px-2">盈亏</th>
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
                  <div key={h.ticker} className="border rounded-lg p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-mono font-semibold">{h.ticker}</span>
                        <span className="text-xs text-muted-foreground ml-1">{h.shares} 股</span>
                      </div>
                      <span className={cn("font-mono text-sm",
                        h.pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        {fmtPct(h.pnl_pct)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>成本 ${fmt(h.avg_cost)}</span>
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
                            <td className="py-2 px-2 text-xs text-muted-foreground font-mono">{t.timestamp?.slice(0, 16)}</td>
                            <td className="py-2 px-2 font-mono font-semibold">{t.ticker}</td>
                            <td className="py-2 px-2">
                              <span className={cn("text-xs font-medium", t.action === "BUY" ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                                {t.action}
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
                      <div key={t.id} className="border rounded-lg p-3">
                        <div className="flex justify-between items-center">
                          <span className="font-mono font-semibold">{t.ticker}</span>
                          <span className={cn("text-xs font-medium", t.action === "BUY" ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                            {t.action} {t.shares} @ ${fmt(t.price)}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{t.timestamp?.slice(0, 16)}</div>
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
      <UpdateCostModal target={costTarget} onClose={() => setCostTarget(null)} onSuccess={load} />
    </div>
  )
}

/* ── Buy Dialog (4 fields: ticker/shares/price/notes) ──────── */

function BuyDialog({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [ticker, setTicker] = useState("")
  const [shares, setShares] = useState("")
  const [price, setPrice] = useState("")
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!ticker || !shares || !price) return
    setSubmitting(true)
    try {
      await apiPost("/api/portfolio/add", {
        ticker, shares: parseFloat(shares), price: parseFloat(price), notes,
      })
      onSuccess()
      onClose()
      setTicker(""); setShares(""); setPrice(""); setNotes("")
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "买入失败")
    }
    setSubmitting(false)
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader><DialogTitle>买入股票</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">股票代码</label>
            <Input placeholder="如 AAPL" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} />
          </div>
          <div className="flex gap-3 form-row-mobile">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">数量</label>
              <Input type="number" placeholder="股数" value={shares} onChange={e => setShares(e.target.value)} />
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">价格</label>
              <Input type="number" placeholder="买入价" step="0.01" value={price} onChange={e => setPrice(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">备注</label>
            <Input placeholder="可选备注" value={notes} onChange={e => setNotes(e.target.value)} />
          </div>
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

/* ── Sell Dialog (4 fields: ticker/shares/price/notes) ──────── */

function SellDialog({ target, onClose, onSuccess }: { target: Holding | null; onClose: () => void; onSuccess: () => void }) {
  const [shares, setShares] = useState("")
  const [price, setPrice] = useState("")
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (target) {
      setShares(String(target.shares))
      setPrice(target.current_price ? String(target.current_price) : "")
      setNotes("")
    }
  }, [target])

  const handleSubmit = async () => {
    if (!target || !shares || !price) return
    setSubmitting(true)
    try {
      await apiPost("/api/portfolio/sell", {
        ticker: target.ticker,
        shares: parseFloat(shares),
        price: parseFloat(price),
        notes,
      })
      onSuccess()
      onClose()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "卖出失败")
    }
    setSubmitting(false)
  }

  return (
    <Dialog open={!!target} onOpenChange={() => onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>卖出 {target?.ticker}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="flex gap-3 form-row-mobile">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">卖出数量</label>
              <Input type="number" placeholder="股数" value={shares} onChange={e => setShares(e.target.value)} />
              <span className="text-xs text-muted-foreground">持有 {target?.shares} 股</span>
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">卖出价格</label>
              <Input type="number" placeholder="卖出价" step="0.01" value={price} onChange={e => setPrice(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">备注</label>
            <Input placeholder="可选备注" value={notes} onChange={e => setNotes(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting} className="bg-[var(--color-accent-red)] hover:bg-[var(--color-accent-red)]/90">
            {submitting ? "提交中..." : "确认卖出"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── Update Cost Modal ──────────────────────────────────────── */

function UpdateCostModal({ target, onClose, onSuccess }: { target: Holding | null; onClose: () => void; onSuccess: () => void }) {
  const [cost, setCost] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (target) setCost(String(target.avg_cost))
  }, [target])

  const handleSubmit = async () => {
    if (!target || !cost) return
    setSubmitting(true)
    try {
      await apiPost("/api/portfolio/update_cost", {
        ticker: target.ticker,
        avg_cost: parseFloat(cost),
      })
      onSuccess()
      onClose()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "修正失败")
    }
    setSubmitting(false)
  }

  return (
    <Dialog open={!!target} onOpenChange={() => onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>修正成本价 — {target?.ticker}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">当前成本</label>
            <div className="text-sm font-mono text-muted-foreground">${target ? fmt(target.avg_cost) : "-"}</div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">新成本价</label>
            <Input type="number" step="0.01" value={cost} onChange={e => setCost(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "提交中..." : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
