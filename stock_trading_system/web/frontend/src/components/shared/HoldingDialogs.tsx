import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import { apiPost } from "@/lib/api"

export interface HoldingTarget {
  ticker: string
  shares: number
  avg_cost: number
  current_price?: number
}

function fmt(n: number) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function BuyDialog({ open, onClose, onSuccess }: {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}) {
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
            <Input placeholder="如 AAPL" value={ticker}
                   onChange={e => setTicker(e.target.value.toUpperCase())} />
          </div>
          <div className="flex gap-3 form-row-mobile">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">数量</label>
              <Input type="number" placeholder="股数" value={shares}
                     onChange={e => setShares(e.target.value)} />
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">价格</label>
              <Input type="number" placeholder="买入价" step="0.01" value={price}
                     onChange={e => setPrice(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">备注</label>
            <Input placeholder="可选备注" value={notes}
                   onChange={e => setNotes(e.target.value)} />
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

export function SellDialog({ target, onClose, onSuccess }: {
  target: HoldingTarget | null
  onClose: () => void
  onSuccess: () => void
}) {
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
              <Input type="number" placeholder="股数" value={shares}
                     onChange={e => setShares(e.target.value)} />
              <span className="text-xs text-muted-foreground">持有 {target?.shares} 股</span>
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">卖出价格</label>
              <Input type="number" placeholder="卖出价" step="0.01" value={price}
                     onChange={e => setPrice(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">备注</label>
            <Input placeholder="可选备注" value={notes}
                   onChange={e => setNotes(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}
                  className="bg-[var(--color-accent-red)] hover:bg-[var(--color-accent-red)]/90">
            {submitting ? "提交中..." : "确认卖出"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function UpdateCostDialog({ target, onClose, onSuccess }: {
  target: HoldingTarget | null
  onClose: () => void
  onSuccess: () => void
}) {
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
            <div className="text-sm font-mono text-muted-foreground">
              ${target ? fmt(target.avg_cost) : "-"}
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">新成本价</label>
            <Input type="number" step="0.01" value={cost}
                   onChange={e => setCost(e.target.value)} />
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
