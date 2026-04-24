import { useEffect, useState } from "react"
import {
  CheckCircle2, Clock4, TrendingUp, AlertCircle,
  Sparkles, ExternalLink, XCircle, Loader2,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

interface PaperPayload {
  session: { id: number; ticker: string; status: string; start_capital: number } | null
  active_plan: {
    id: number; rating: string; thesis: string; analysis_id: number
    holding_months_min: number | null; holding_months_max: number | null
    parse_method: string; created_at: string; trade_decision?: string
  } | null
  active_orders: Order[]
  plan_history: Plan[]
  events: Event[]
  dailies: Daily[]
  latest_trade_decision: string | null
  latest_advice: { action: string; reasoning: string } | null
}

interface Order {
  id: number; order_type: string; sequence: number; pct_target_total: number
  trigger_kind: string; trigger_json: string; status: string
  triggered_date: string | null; triggered_price: number | null; description: string
}

interface Plan {
  id: number; rating: string; thesis: string; analysis_id: number
  created_at: string; status: string; trade_decision?: string; orders: Order[]
}

interface Event {
  id: number; event_type: string; analysis_id: number; ticker: string
  signal: string; created_at: string
}

interface Daily {
  date: string; close_price: number; total_value: number; daily_pnl: number
  cum_pnl_pct: number; drawdown_pct: number
}

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }

const ORDER_LABELS: Record<string, string> = {
  entry_initial: "初始建仓", entry_add: "加仓档",
  exit_stop: "硬性止损", exit_target: "止盈档", exit_trailing: "跟踪止盈",
}
const STATUS_ICONS: Record<string, React.ReactNode> = {
  triggered: <CheckCircle2 className="w-4 h-4 text-green-500" />,
  pending: <Clock4 className="w-4 h-4 text-muted-foreground" />,
  superseded: <XCircle className="w-4 h-4 text-muted-foreground opacity-50" />,
  cancelled: <XCircle className="w-4 h-4 text-red-500" />,
}

export function PaperTradePage() {
  const ticker = window.location.pathname.split("/").pop()?.toUpperCase() || ""
  const [data, setData] = useState<PaperPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [recordView, setRecordView] = useState<"plan" | "event">("plan")

  useEffect(() => {
    if (!ticker) { setError("未指定股票代码"); setLoading(false); return }
    apiGet<PaperPayload>(`/api/paper/tickers/${ticker}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message || "加载失败"); setLoading(false) })
  }, [ticker])

  if (loading) return <LoadingSkeleton />
  if (error) return (
    <div className="p-6 max-w-3xl mx-auto">
      <Alert variant="destructive"><AlertCircle className="w-4 h-4" /> {error}</Alert>
    </div>
  )
  if (!data || !data.session) return (
    <div className="p-6 max-w-3xl mx-auto">
      <Alert>未找到 {ticker} 的纸面交易会话</Alert>
    </div>
  )

  const plan = data.active_plan
  const orders = data.active_orders || []
  const sess = data.session

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">{ticker} 纸面交易</h1>
        <Badge variant={sess.status === "running" ? "default" : "secondary"}>{sess.status}</Badge>
      </div>

      {/* Strategy + Position */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Current Strategy */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">当前策略</CardTitle>
              {plan && <Badge variant={plan.rating === "BUY" || plan.rating === "Buy" ? "buy" : plan.rating === "SELL" ? "sell" : "secondary"}>
                {plan.rating || "—"}
              </Badge>}
            </div>
          </CardHeader>
          <CardContent>
            {plan ? (
              <div className="space-y-2">
                {plan.thesis && <p className="text-sm">{plan.thesis}</p>}
                <div className="text-xs text-muted-foreground">
                  分析 #{plan.analysis_id} · {plan.created_at} · {plan.parse_method}
                  {plan.holding_months_min && ` · ${plan.holding_months_min}-${plan.holding_months_max || "?"}个月`}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">暂无活跃策略</p>
            )}
          </CardContent>
        </Card>

        {/* Position */}
        <Card>
          <CardHeader><CardTitle className="text-sm">持仓状态</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <div className="text-muted-foreground">初始资金</div>
              <div className="font-mono text-right">${fmt(sess.start_capital)}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Order Tiers */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">计划档位（已执行 / 待触发）</CardTitle>
            <span className="text-xs text-muted-foreground">
              {orders.filter(o => o.status === "triggered").length} 触发 · {orders.filter(o => o.status === "pending").length} 待触发
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {orders.length === 0 ? (
            <p className="text-sm text-muted-foreground">无计划档位</p>
          ) : (
            <div className="space-y-2">
              {orders.sort((a, b) => a.sequence - b.sequence).map(o => (
                <div key={o.id} className={cn(
                  "flex items-center gap-3 rounded-lg border px-4 py-3",
                  o.status === "triggered" ? "border-green-500/30 bg-green-500/5" : "border-border",
                )}>
                  {STATUS_ICONS[o.status] || <Clock4 className="w-4 h-4" />}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{ORDER_LABELS[o.order_type] || o.order_type}</div>
                    <div className="text-xs text-muted-foreground">{o.description || o.trigger_kind}</div>
                  </div>
                  {o.pct_target_total > 0 && (
                    <span className="text-xs font-mono">{o.pct_target_total}%</span>
                  )}
                  {o.triggered_date && (
                    <span className="text-xs text-muted-foreground">{o.triggered_date} @ ${o.triggered_price}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* AI 最终决策 */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-blue-500" />
            <CardTitle className="text-sm">AI 最终决策</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          {data.latest_trade_decision ? (
            <div className="text-sm leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto">
              {data.latest_trade_decision}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无决策原文</p>
          )}
        </CardContent>
      </Card>

      {/* 执行记录（按 Plan / 按 Event） */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">执行记录</CardTitle>
            <ChipRow>
              <Chip active={recordView === "plan"} onClick={() => setRecordView("plan")}>按 Plan</Chip>
              <Chip active={recordView === "event"} onClick={() => setRecordView("event")}>按 Event</Chip>
            </ChipRow>
          </div>
        </CardHeader>
        <CardContent>
          {recordView === "plan" ? (
            <PlanHistory plans={data.plan_history || []} />
          ) : (
            <EventTimeline events={data.events || []} />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PlanHistory({ plans }: { plans: Plan[] }) {
  if (!plans.length) return <p className="text-sm text-muted-foreground">暂无策略记录</p>
  return (
    <div className="space-y-3">
      {plans.map(p => (
        <div key={p.id} className={cn(
          "rounded-lg border p-3",
          p.status === "active" ? "border-primary/30" : "border-border opacity-70",
        )}>
          <div className="flex items-center gap-2 mb-1">
            <Badge variant={p.status === "active" ? "default" : "secondary"}>
              {p.rating || "—"}
            </Badge>
            <span className="text-xs font-medium">Plan #{p.id}</span>
            {p.status === "active" && <Badge variant="outline" className="text-[10px]">当前</Badge>}
            <span className="text-xs text-muted-foreground ml-auto">{p.created_at}</span>
          </div>
          {p.thesis && <p className="text-xs text-muted-foreground mb-1">{p.thesis}</p>}
          {p.trade_decision && (
            <details className="mt-2">
              <summary className="text-xs text-primary cursor-pointer">AI 最终决策原文</summary>
              <div className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap max-h-40 overflow-y-auto">
                {p.trade_decision}
              </div>
            </details>
          )}
        </div>
      ))}
    </div>
  )
}

function EventTimeline({ events }: { events: Event[] }) {
  if (!events.length) return <p className="text-sm text-muted-foreground">暂无事件</p>
  return (
    <div className="space-y-2">
      {events.map(e => (
        <div key={e.id} className="flex items-center gap-3 text-sm border-b border-border/50 pb-2">
          <Badge variant={e.signal === "BUY" ? "buy" : e.signal === "SELL" ? "sell" : "secondary"} className="text-[10px]">
            {e.signal}
          </Badge>
          <span className="text-xs text-muted-foreground">{e.created_at}</span>
          <span className="text-xs">{e.event_type}</span>
        </div>
      ))}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
      <Skeleton className="h-60" />
      <Skeleton className="h-48" />
    </div>
  )
}
