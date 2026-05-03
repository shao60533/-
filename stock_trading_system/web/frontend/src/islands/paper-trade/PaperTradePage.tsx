import React, { useEffect, useState, useMemo } from "react"
import {
  CheckCircle2, Clock4, AlertCircle,
  Sparkles, XCircle, BarChart3, ScrollText,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import type { EChartsOption } from "@/lib/echarts"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"
// paper-trade v1.4: same banner shape as /analysis/<id>; raw
// trade_decision markdown no longer surfaces on /paper-trade/<ticker>.
import {
  signalLabel,
  signalVariant,
} from "@/islands/analysis/AnalysisPage"
import { ConfidenceMeter } from "@/components/analysis/shared/ConfidenceMeter"

const ChartPanel = React.lazy(() =>
  import("@/components/shared/ChartPanel").then(m => ({ default: m.ChartPanel })),
)

// paper-trade v1.4: shared banner DTO mirrored from
// _rendering_summary_for_analysis (web/app.py).
export interface AnalysisSummary {
  analysis_id: number
  ticker?: string | null
  date?: string | null
  created_at?: string | null
  signal_raw?: string | null
  signal_tri?: "Buy" | "Sell" | "Hold"
  rating?: string | null
  action_direction?: string | null
  executive_summary?: string | null
  one_line_takeaway?: string | null
  confidence_pct?: number | null
  confidence_level?: "high" | "medium" | "low" | null
}

interface ActivePlan {
  id: number; rating: string; thesis: string; analysis_id: number
  holding_months_min: number | null; holding_months_max: number | null
  parse_method: string; created_at: string
  analysis_summary?: AnalysisSummary | null
  holding_months?: string | null
}

interface PaperPayload {
  session: { id: number; ticker: string; status: string; start_capital: number } | null
  active_plan: ActivePlan | null
  active_orders: Order[]
  plan_history: Plan[]
  events: Event[]
  dailies: Daily[]
  latest_trade_decision: string | null
  latest_analysis_summary?: AnalysisSummary | null
  latest_advice: { action: string; reasoning: string } | null
}

interface Order {
  id: number; order_type: string; sequence: number; pct_target_total: number
  trigger_kind: string; trigger_json: string; status: string
  triggered_date: string | null; triggered_price: number | null; description: string
}

interface Plan {
  id: number; rating: string; thesis: string; analysis_id: number
  created_at: string; status: string; orders: Order[]
  // paper-trade v1.4: rendering banner DTO (replaces raw trade_decision).
  analysis_summary?: AnalysisSummary | null
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
        {/* paper-trade v1.4: ``当前策略`` mirrors /analysis/<id> banner. */}
        <ActiveStrategyCard
          plan={data.active_plan}
          fallback={data.latest_analysis_summary ?? null}
        />

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

      {/* paper-trade v1.4: "AI 最终决策" card removed — its content
          (raw trade_decision markdown) is already rendered on
          /analysis/<id>, and the ActiveStrategyCard above + the
          AnalysisHistoryList below both link there. */}

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
            <AnalysisHistoryList plans={data.plan_history || []} />
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
          <React.Suspense fallback={<Skeleton className="h-[360px] w-full" />}>
            <ChartPanel option={chartOption} height={360} loading={dailies.length === 0} />
          </React.Suspense>
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

/* ── paper-trade v1.4 — banner + history mirroring /analysis/<id> ───── */

/** ActiveStrategyCard renders the OverviewCard-style banner (Rating
 *  Badge + tri-state signal + ConfidenceMeter + executive summary)
 *  inside the strategy column. Falls back to ``latest_analysis_summary``
 *  when no plan exists; renders nothing when both are missing. */
export function ActiveStrategyCard({
  plan,
  fallback,
}: {
  plan: ActivePlan | null
  fallback: AnalysisSummary | null
}) {
  const summary = plan?.analysis_summary ?? fallback ?? null
  if (!plan && !summary) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">当前策略</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            {summary?.signal_raw && (
              <Badge variant={signalVariant(summary.signal_raw)}>
                {signalLabel(summary.signal_raw)}
              </Badge>
            )}
            {summary?.rating && (
              <Badge variant="outline" className="font-semibold">
                {summary.rating}
              </Badge>
            )}
            {summary?.confidence_level && (
              <ConfidenceMeter level={summary.confidence_level} />
            )}
          </div>
          {summary?.analysis_id && (
            <a
              href={`/analysis/${summary.analysis_id}`}
              className="text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              查看完整分析 →
            </a>
          )}
        </div>

        {summary?.action_direction && (
          <div className="text-base font-medium">📍 {summary.action_direction}</div>
        )}

        {summary?.executive_summary ? (
          <div className="border-l-4 border-primary/60 bg-primary/5 pl-3 py-2">
            <div className="flex items-center gap-2 text-sm font-semibold mb-1">
              <ScrollText className="h-4 w-4" />
              执行总结
            </div>
            <p className="text-sm leading-relaxed line-clamp-4">
              {summary.executive_summary}
            </p>
          </div>
        ) : summary?.one_line_takeaway ? (
          <p className="text-sm text-muted-foreground">{summary.one_line_takeaway}</p>
        ) : null}

        {plan && (
          <div className="text-xs text-muted-foreground border-t pt-3 flex items-center gap-2 flex-wrap">
            <span>策略 #{plan.id}</span>
            {plan.created_at && (
              <>
                <span>·</span>
                <span>{plan.created_at}</span>
              </>
            )}
            {plan.holding_months && (
              <>
                <span>·</span>
                <span>持有 {plan.holding_months} 个月</span>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** AnalysisHistoryList replaces the v1.3 PlanHistory component for the
 *  "执行记录·按 Plan" tab. Each row is a clickable link to
 *  ``/analysis/<id>``; topmost row is flagged ``★ 当前``. Rows whose
 *  linked analysis lacks a rendering banner show a degraded
 *  "(结构化数据缺失)" hint instead of leaking raw markdown. */
export function AnalysisHistoryList({ plans }: { plans: Plan[] }) {
  if (plans.length === 0) {
    return <p className="text-sm text-muted-foreground">尚无分析记录</p>
  }
  return (
    <div className="divide-y">
      {plans.map((p, idx) => {
        const summary = p.analysis_summary
        const isActive = idx === 0
        const href = summary?.analysis_id
          ? `/analysis/${summary.analysis_id}`
          : (p.analysis_id ? `/analysis/${p.analysis_id}` : "#")
        return (
          <a
            key={p.id}
            href={href}
            className="block py-3 px-2 hover:bg-accent transition-colors"
          >
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              {isActive && <Badge variant="default">★ 当前</Badge>}
              {summary?.signal_raw && (
                <Badge
                  variant={signalVariant(summary.signal_raw)}
                  className="text-xs"
                >
                  {signalLabel(summary.signal_raw)}
                </Badge>
              )}
              {summary?.rating && (
                <Badge variant="outline" className="text-xs">
                  {summary.rating}
                </Badge>
              )}
              {typeof summary?.confidence_pct === "number" && (
                <span className="text-xs text-muted-foreground">
                  置信 {summary.confidence_pct}%
                </span>
              )}
              <span className="text-xs text-muted-foreground ml-auto">
                {summary?.created_at ?? p.created_at ?? ""}
              </span>
            </div>
            {summary?.action_direction && (
              <div className="text-sm font-medium mb-1">
                📍 {summary.action_direction}
              </div>
            )}
            {(summary?.executive_summary || summary?.one_line_takeaway) && (
              <p className="text-xs text-muted-foreground line-clamp-2">
                {summary?.executive_summary || summary?.one_line_takeaway}
              </p>
            )}
            {!summary && (
              <p className="text-xs text-muted-foreground">
                分析 #{p.analysis_id ?? "—"}（结构化数据缺失）
              </p>
            )}
          </a>
        )
      })}
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
