import { useEffect, useState } from "react"
import { TestTube, Search, RefreshCw } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/api"

type Mode = "forward" | "replay"

interface TickerSession {
  id: number
  ticker: string
  status: string
  start_date: string
  last_eod: string | null
  current_signal: string | null
  current_action: string | null
  total_value: number
  cum_pnl_pct: number
  position_shares: number
  close_price: number | null
  num_events: number
  hit_rate: number | null
  hit_pretty: string
  sparkline: number[]
  active_plan_count: number
  pending_orders_count: number
  triggered_orders_count: number
  open_position_shares: number | null
  last_skip_reason: string | null
  // v1.21: ticker aggregation. ``id`` is the canonical (earliest)
  // session for the (user, ticker); ``session_ids`` lists every
  // sibling that was rolled into this card; ``analysis_count`` is
  // the total number of analyses across siblings.
  session_ids?: number[]
  latest_session_id?: number
  analysis_count?: number
  latest_analysis_at?: string | null
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${(n * 100).toFixed(2)}%`
}

function fmtMoney(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

export function PaperTradeListPage() {
  const [mode, setMode] = useState<Mode>("forward")
  const [tickers, setTickers] = useState<TickerSession[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")

  const load = async (m: Mode = mode) => {
    setLoading(true)
    try {
      const data = await apiGet<TickerSession[]>(`/api/paper/tickers?mode=${m}`)
      setTickers(Array.isArray(data) ? data : [])
    } catch {
      setTickers([])
    }
    setLoading(false)
  }

  useEffect(() => {
    load(mode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  const filtered = tickers.filter(t => {
    if (!search) return true
    return t.ticker.toLowerCase().includes(search.toLowerCase())
  })

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <TestTube className="w-5 h-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">纸面交易</h1>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="搜索代码..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <ChipRow>
          <Chip active={mode === "forward"} onClick={() => setMode("forward")}>
            前向追踪
          </Chip>
          <Chip active={mode === "replay"} onClick={() => setMode("replay")}>
            历史回放
          </Chip>
        </ChipRow>
        <Button variant="outline" size="sm" onClick={() => load()}>
          <RefreshCw className="w-4 h-4 mr-1" /> 刷新
        </Button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-44" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          {mode === "forward" ? "暂无前向追踪会话" : "暂无历史回放"}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(t => <TickerCard key={t.id} t={t} />)}
        </div>
      )}
    </div>
  )
}

function TickerCard({ t }: { t: TickerSession }) {
  return (
    <a
      href={`/paper-trade/${t.ticker}`}
      className="block focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-blue)] rounded-md"
    >
      <Card className="hover:border-[var(--color-border-bright)] transition-colors">
        <CardContent className="pt-5 space-y-2">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <span className="font-mono font-semibold truncate">{t.ticker}</span>
            <Badge
              variant={t.status === "running" ? "default" : "muted"}
              className="text-[10px] shrink-0"
            >
              {t.status}
            </Badge>
            {t.current_signal && (
              <Badge variant="outline" className="text-[10px] shrink-0">
                {t.current_signal}
              </Badge>
            )}
          </div>

          <div className="text-xs text-muted-foreground">
            起始 {t.start_date}
            {t.last_eod && <span className="ml-2">EOD {t.last_eod}</span>}
          </div>

          {/* Mobile: PnL pct wraps to its own line so a long
              total_value never pushes it off the card. flex-wrap +
              min-w-0 keeps both pieces fully visible at 320px. */}
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 min-w-0">
            <span className="text-lg font-mono truncate">${fmtMoney(t.total_value)}</span>
            <span
              className={
                t.cum_pnl_pct > 0 ? "text-[var(--color-accent-green)] text-sm" :
                t.cum_pnl_pct < 0 ? "text-[var(--color-accent-red)] text-sm" :
                "text-muted-foreground text-sm"
              }
            >
              {fmtPct(t.cum_pnl_pct / 100)}
            </span>
          </div>

          <div className="text-xs space-y-0.5 text-muted-foreground">
            <div>
              历史分析 {t.analysis_count ?? t.num_events ?? 0} 次
            </div>
            <div>
              Plan: {t.active_plan_count} active
            </div>
            <div>
              Orders: {t.pending_orders_count} pending · {t.triggered_orders_count} triggered
            </div>
            <div>
              Pos: {t.open_position_shares != null
                ? `${t.open_position_shares} shares`
                : "—"}
            </div>
            {t.last_skip_reason && (
              <div className="pt-1 min-w-0">
                {/* `whitespace-normal` overrides the Badge default
                    nowrap so a long skip reason wraps inside the
                    badge rather than pushing past the card edge. */}
                <Badge variant="outline" className="text-[10px] max-w-full whitespace-normal text-left leading-snug py-1 break-words">
                  跳过: {t.last_skip_reason}
                </Badge>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </a>
  )
}
