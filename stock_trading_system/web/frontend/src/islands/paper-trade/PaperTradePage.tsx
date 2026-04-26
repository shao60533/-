import React, { useEffect, useState, useMemo } from "react"
import {
  CheckCircle2, Clock4, AlertCircle,
  Sparkles, XCircle, BarChart3,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import { ChartPanel } from "@/components/shared/ChartPanel"
import type { EChartsOption } from "@/lib/echarts"
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
  return (
    <ErrorBoundary>
      <PaperTradeContent />
    </ErrorBoundary>
  )
}

function ErrorBoundary({ children }: { children: React.ReactNode }) {
  const [hasError, setHasError] = useState(false)
  if (hasError) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <Alert><AlertCircle className="w-4 h-4" /> 页面渲染异常，请刷新</Alert>
        <Button variant="outline" className="mt-4" onClick={() => window.location.reload()}>刷新页面</Button>
      </div>
    )
  }
  return (
    <ErrorCatcher onError={() => setHasError(true)}>{children}</ErrorCatcher>
  )
}

class ErrorCatcher extends React.Component<{ children: React.ReactNode; onError: () => void }> {
  componentDidCatch() { this.props.onError() }
  render() { return this.props.children }
}

function PaperTradeContent() {
  const m = window.location.pathname.match(/\/paper-trade\/([^/?#]+)/)
  const ticker = m?.[1]?.toUpperCase() || ""
  const [data, setData] = useState<PaperPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [recordView, setRecordView] = useState<"plan" | "event">("plan")
  // mainTab MUST be declared before any conditional return — otherwise React
  // re-renders this component with a different number of hooks, throws
  // "Rendered more hooks than during the previous render", and the
  // ErrorBoundary upstream shows "页面渲染异常" instead of the real UI.
  const [mainTab, setMainTab] = useState<"strategy" | "daily">("strategy")

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
  const orders = data.active_orders ?? []
  const sess = data.session

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">{ticker} 纸面交易</h1>
        <Badge variant={sess.status === "running" ? "default" : "muted"}>{sess.status}</Badge>
      </div>

      {/* Main tab switch */}
      <ChipRow>
        <Chip active={mainTab === "strategy"} onClick={() => setMainTab("strategy")}>
          <Sparkles className="w-3.5 h-3.5 mr-1" />策略
        </Chip>
        <Chip active={mainTab === "daily"} onClick={() => setMainTab("daily")}>
          <BarChart3 className="w-3.5 h-3.5 mr-1" />日度数据
        </Chip>
      </ChipRow>

      {mainTab === "daily" && <DailyDataTab dailies={data.dailies ?? []} startCapital={sess.start_capital ?? 0} />}
      {mainTab === "strategy" && (<>
      {/* BEGIN strategy tab */}

      {/* Strategy + Position */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Current Strategy */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">当前策略</CardTitle>
              {plan && <Badge variant={plan.rating === "BUY" || plan.rating === "Buy" ? "buy" : plan.rating === "SELL" ? "sell" : "muted"}>
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
              <div className="font-mono text-right">${fmt(sess.start_capital ?? 0)}</div>
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
              {[...orders]
                .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
                .map(o => (
                  <div key={o.id} className={cn(
                    "flex items-center gap-3 rounded-lg border px-4 py-3",
                    o.status === "triggered" ? "border-green-500/30 bg-green-500/5" : "border-border",
                  )}>
                    {STATUS_ICONS[o.status] ?? <Clock4 className="w-4 h-4" />}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium">
                        {ORDER_LABELS[o.order_type] ?? (o.order_type || "—")}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {o.description || o.trigger_kind || ""}
                      </div>
                    </div>
                    {(o.pct_target_total ?? 0) > 0 && (
                      <span className="text-xs font-mono">{o.pct_target_total}%</span>
                    )}
                    {o.triggered_date && (
                      <span className="text-xs text-muted-foreground">
                        {o.triggered_date} @ ${o.triggered_price ?? "—"}
                      </span>
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
      {/* END strategy tab */}
      </>)}
    </div>
  )
}

/* ── Daily Data Tab ─────────────────────────────────────────── */

function DailyDataTab({ dailies }: { dailies: Daily[]; startCapital: number }) {
  const latest = dailies.length > 0 ? dailies[dailies.length - 1] : null
  const maxDrawdown = dailies.length > 0 ? Math.min(...dailies.map(d => d.drawdown_pct)) : 0

  const chartOption = useMemo((): EChartsOption | null => {
    if (dailies.length === 0) return null
    const dates = dailies.map(d => d.date)
    const values = dailies.map(d => d.total_value)
    const drawdowns = dailies.map(d => d.drawdown_pct)

    // Find drawdown areas (continuous negative drawdown)
    const markAreas: [{ xAxis: string }, { xAxis: string }][] = []
    let areaStart: string | null = null
    for (let i = 0; i < dailies.length; i++) {
      if (dailies[i].drawdown_pct < -1) {
        if (!areaStart) areaStart = dailies[i].date
      } else if (areaStart) {
        markAreas.push([{ xAxis: areaStart }, { xAxis: dailies[i - 1].date }])
        areaStart = null
      }
    }
    if (areaStart) markAreas.push([{ xAxis: areaStart }, { xAxis: dailies[dailies.length - 1].date }])

    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: [
        { left: 60, right: 20, top: 30, height: "55%" },
        { left: 60, right: 20, top: "75%", height: "18%" },
      ],
      xAxis: [
        { type: "category", data: dates, gridIndex: 0, axisLine: { lineStyle: { color: "#444" } } },
        { type: "category", data: dates, gridIndex: 1, axisLine: { lineStyle: { color: "#444" } } },
      ],
      yAxis: [
        { type: "value", gridIndex: 0, axisLabel: { formatter: (v: number) => `$${(v/1000).toFixed(0)}k` }, splitLine: { lineStyle: { color: "#222" } } },
        { type: "value", gridIndex: 1, axisLabel: { formatter: (v: number) => `${v.toFixed(0)}%` }, splitLine: { lineStyle: { color: "#222" } } },
      ],
      series: [
        {
          name: "权益", type: "line", data: values, smooth: true,
          lineStyle: { color: "#3882ff", width: 2 },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(56,130,255,0.25)" }, { offset: 1, color: "rgba(56,130,255,0)" }] } },
          markArea: markAreas.length > 0 ? {
            silent: true,
            itemStyle: { color: "rgba(255,56,96,0.08)" },
            data: markAreas as any,
          } : undefined,
        },
        {
          name: "回撤%", type: "bar", data: drawdowns, xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: { color: "#ff3860" },
        },
      ],
    }
  }, [dailies])

  return (
    <div className="space-y-4">
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 grid-collapse-mobile">
        <Stat label="当前净值" value={latest ? `$${fmt(latest.total_value)}` : "-"} />
        <Stat label="累计收益" value={latest ? `${latest.cum_pnl_pct.toFixed(2)}%` : "-"}
              delta={latest?.cum_pnl_pct} />
        <Stat label="最大回撤" value={`${maxDrawdown.toFixed(2)}%`} />
        <Stat label="交易天数" value={String(dailies.length)} />
      </div>

      {/* Equity chart */}
      <Card>
        <CardHeader><CardTitle className="text-sm">权益曲线</CardTitle></CardHeader>
        <CardContent>
          <ChartPanel option={chartOption} height={360} loading={dailies.length === 0} />
        </CardContent>
      </Card>

      {/* Daily table / mobile cards */}
      <Card>
        <CardHeader><CardTitle className="text-sm">日度明细</CardTitle></CardHeader>
        <CardContent>
          {dailies.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">暂无日度数据</p>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs uppercase">
                      <th className="text-left py-2 px-2">日期</th>
                      <th className="text-right py-2 px-2">收盘</th>
                      <th className="text-right py-2 px-2">总值</th>
                      <th className="text-right py-2 px-2">日 PnL</th>
                      <th className="text-right py-2 px-2">累计%</th>
                      <th className="text-right py-2 px-2">回撤%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...dailies].reverse().slice(0, 30).map(d => (
                      <tr key={d.date} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2 px-2 font-mono text-xs">{d.date}</td>
                        <td className="text-right py-2 px-2 font-mono">${fmt(d.close_price)}</td>
                        <td className="text-right py-2 px-2 font-mono">${fmt(d.total_value)}</td>
                        <td className={cn("text-right py-2 px-2 font-mono", d.daily_pnl >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                          ${fmt(d.daily_pnl)}
                        </td>
                        <td className={cn("text-right py-2 px-2 font-mono", d.cum_pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                          {d.cum_pnl_pct.toFixed(2)}%
                        </td>
                        <td className="text-right py-2 px-2 font-mono text-[var(--color-accent-red)]">
                          {d.drawdown_pct.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden space-y-2">
                {[...dailies].reverse().slice(0, 20).map(d => (
                  <div key={d.date} className="border rounded-lg p-3">
                    <div className="flex justify-between items-center">
                      <span className="font-mono text-xs">{d.date}</span>
                      <span className={cn("font-mono text-sm", d.daily_pnl >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        ${fmt(d.daily_pnl)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>净值 ${fmt(d.total_value)}</span>
                      <span>累计 {d.cum_pnl_pct.toFixed(2)}%</span>
                      <span>回撤 {d.drawdown_pct.toFixed(2)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
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
            <Badge variant={p.status === "active" ? "default" : "muted"}>
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
          <Badge variant={e.signal === "BUY" ? "buy" : e.signal === "SELL" ? "sell" : "muted"} className="text-[10px]">
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
