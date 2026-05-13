import React, { useEffect, useState, useMemo } from "react"
import {
  CheckCircle2, Clock4, AlertCircle,
  Sparkles, XCircle,
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
import { apiGet, apiPost } from "@/lib/api"
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
  // mobile-ui-v1.3: top-level 策略 / 日度数据 inner tabs are removed.
  // The detail page renders strategy + daily content stacked so users
  // never have to switch tabs to see plan + EOD on the same screen.

  // paper-trade v1.5: extracted into a function so the EOD refresh
  // button on the daily tab can re-pull after triggering /api/paper/
  // tickers/<t>/eod. Initial mount still fires inside useEffect.
  const refresh = () => {
    if (!ticker) return
    return apiGet<PaperPayload>(`/api/paper/tickers/${ticker}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message || "加载失败"); setLoading(false) })
  }
  useEffect(() => {
    if (!ticker) { setError("未指定股票代码"); setLoading(false); return }
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    <div className="p-4 md:p-6 space-y-6 max-w-5xl mx-auto min-w-0">
      <Button variant="ghost" size="sm" onClick={() => window.location.href = "/paper-trade"}
              className="-ml-2 self-start">
        ← 返回纸面交易
      </Button>
      <div className="mobile-card-header">
        <h1 className="mc-title text-xl font-bold truncate">{ticker} 纸面交易 · 详情</h1>
        <div className="mc-actions">
          <Badge variant={sess.status === "running" ? "default" : "muted"}>{sess.status}</Badge>
        </div>
      </div>

      {/* mobile-ui-v1.3: 策略 / 日度数据 inner tabs removed. Strategy
          + position + plan tiers + daily-data + AI decision + execution
          records render stacked in document order. */}

      {/* Strategy + Position */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Current Strategy */}
        <Card>
          <CardHeader>
            <div className="mobile-card-header">
              <CardTitle className="mc-title text-sm truncate">当前策略</CardTitle>
              {plan && (
                <div className="mc-actions">
                  <Badge variant={plan.rating === "BUY" || plan.rating === "Buy" ? "buy" : plan.rating === "SELL" ? "sell" : "muted"}>
                    {plan.rating || "—"}
                  </Badge>
                </div>
              )}
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
          <div className="mobile-card-header">
            <CardTitle className="mc-title text-sm truncate">计划档位（已执行 / 待触发）</CardTitle>
            <span className="mc-actions text-xs text-muted-foreground">
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
                  // Mobile: split tier rows into two visual lines —
                  // status-icon + label/description on row 1, pct +
                  // trigger metadata on row 2 (sm:flex-row brings it
                  // back to single-line on tablets+).
                  <div key={o.id} className={cn(
                    "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-3 min-w-0",
                    o.status === "triggered" ? "border-green-500/30 bg-green-500/5" : "border-border",
                  )}>
                    <div className="shrink-0">
                      {STATUS_ICONS[o.status] ?? <Clock4 className="icon-fixed" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {ORDER_LABELS[o.order_type] ?? (o.order_type || "—")}
                      </div>
                      <div className="text-xs text-muted-foreground text-safe text-safe--wrap">
                        {o.description || o.trigger_kind || ""}
                      </div>
                    </div>
                    {(o.pct_target_total ?? 0) > 0 && (
                      <span className="text-xs font-mono shrink-0">
                        {/* paper-trade v1.5: pct_target_total is 0..1
                            fraction; render as integer percent so
                            ``0.10`` shows as ``10%`` not ``0.1%``. */}
                        {((o.pct_target_total ?? 0) * 100).toFixed(0)}%
                      </span>
                    )}
                    {o.triggered_date && (
                      <span className="text-xs text-muted-foreground shrink-0">
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
      {/* 日度数据 — chart + EOD refresh + stat row + table. */}
      <DailyDataTab
        ticker={ticker}
        dailies={data.dailies ?? []}
        startCapital={sess.start_capital ?? 0}
        hasActivePlan={!!data.active_plan}
        onRefresh={() => refresh()}
      />

      {/* AI 决策核心 / 执行记录 — structured panel replaces the raw
          English ``FINAL TRANSACTION PROPOSAL`` blob. Falls back to a
          placeholder when the parsed advice payload is missing. */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-blue-500" />
            <CardTitle className="text-sm">AI 决策核心 / 执行记录</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <StructuredDecisionPanel data={data} />

          <div className="space-y-2">
            <ChipRow>
              <Chip active={recordView === "plan"} onClick={() => setRecordView("plan")}>按 Plan</Chip>
              <Chip active={recordView === "event"} onClick={() => setRecordView("event")}>按 Event</Chip>
            </ChipRow>
            {recordView === "plan" ? (
              <PlanHistory plans={data.plan_history || []} />
            ) : (
              <EventTimeline events={data.events || []} />
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Structured AI decision panel ──────────────────────────────
   Renders score / action / confidence / risk / execution method +
   evidence list, sourced from the parsed ``advice`` payload on the
   active plan. We never render ``latest_trade_decision`` raw text —
   that's English boilerplate from the trader prompt. */

interface StructuredAdvice {
  action?: string
  rating?: string
  confidence?: number
  risk_level?: string
  reasoning?: string
  evidence?: string[]
  thesis?: string
  score?: number
}

function StructuredDecisionPanel({ data }: { data: PaperPayload }) {
  const plan = data.active_plan
  const advice = data.latest_advice as StructuredAdvice | null
  const action = (advice?.action || plan?.rating || "—").toUpperCase()
  const confidence = typeof advice?.confidence === "number" ? advice.confidence : null
  const risk = advice?.risk_level || "—"
  const planRef = plan ? `Plan #${plan.id}` : "—"
  const reasoning = advice?.reasoning || plan?.thesis || ""
  const evidence = Array.isArray(advice?.evidence) ? advice!.evidence! : []
  const score = typeof advice?.score === "number"
    ? Math.round(advice.score)
    : (typeof confidence === "number" ? Math.round(confidence * 100) : null)

  if (!plan && !advice) {
    return <p className="text-sm text-muted-foreground">暂无 AI 决策数据</p>
  }

  const actionVariant =
    action.includes("BUY") ? "buy" :
    action.includes("SELL") ? "sell" :
    "muted" as const

  return (
    <div className="rounded-lg border border-border p-3 space-y-3">
      <div className="flex items-start gap-3">
        {score != null && (
          <div className="shrink-0 w-12 h-12 rounded-full border-2 border-primary/40 flex items-center justify-center font-mono text-sm font-semibold">
            {score}
          </div>
        )}
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <strong className="text-sm">交易决策</strong>
            <Badge variant={actionVariant}>{action}</Badge>
          </div>
          {reasoning && (
            <p className="text-xs text-muted-foreground break-words">{reasoning}</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
        <div className="min-w-0">
          <span className="text-muted-foreground">置信度</span>
          <div className="font-mono truncate">
            {confidence != null ? `${Math.round(confidence * 100)}%` : "—"}
          </div>
        </div>
        <div className="min-w-0">
          <span className="text-muted-foreground">风险等级</span>
          <div className="truncate">{risk}</div>
        </div>
        <div className="min-w-0">
          <span className="text-muted-foreground">执行方式</span>
          <div className="font-mono truncate">{planRef}</div>
        </div>
      </div>

      {evidence.length > 0 && (
        <ul className="space-y-1 text-xs">
          {evidence.slice(0, 6).map((e, i) => (
            <li key={i} className="pl-2 border-l-2 border-primary/40 break-words">{e}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ── Daily Data Tab ─────────────────────────────────────────── */

function DailyDataTab({ ticker, dailies, hasActivePlan, onRefresh }: {
  ticker: string
  dailies: Daily[]
  startCapital: number
  hasActivePlan: boolean
  onRefresh: () => void | Promise<unknown>
}) {
  const latest = dailies.length > 0 ? dailies[dailies.length - 1] : null
  const maxDrawdown = dailies.length > 0 ? Math.min(...dailies.map(d => d.drawdown_pct)) : 0
  const [eodBusy, setEodBusy] = useState(false)
  const [eodMsg, setEodMsg] = useState<string | null>(null)

  const runEod = async () => {
    if (!ticker || eodBusy) return
    setEodBusy(true)
    setEodMsg(null)
    try {
      const res = await apiPost<{ ok: boolean; new_rows?: number; error?: string }>(
        `/api/paper/tickers/${ticker}/eod`, {},
      )
      if (res.ok) {
        setEodMsg(`已刷新 ${res.new_rows ?? 0} 条日度数据`)
        await onRefresh()
      } else {
        setEodMsg(res.error || "EOD 刷新失败")
      }
    } catch (e) {
      setEodMsg((e as Error)?.message || "EOD 刷新失败")
    } finally {
      setEodBusy(false)
    }
  }

  // v1.6 mobile chart sizing: track viewport ≤575.98px so the ECharts
  // ``grid`` margins shrink (60→32 left, 20→8 right) and the panel
  // height drops to 280 to keep the stat row + chart on one fold.
  // ``useState`` initialised lazily so SSR / first paint matches the
  // matchMedia state without a mid-render flicker.
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined"
      && window.matchMedia?.("(max-width: 575.98px)").matches,
  )
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const mq = window.matchMedia("(max-width: 575.98px)")
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener?.("change", handler)
    return () => mq.removeEventListener?.("change", handler)
  }, [])

  const chartOption = useMemo((): EChartsOption | null => {
    if (dailies.length === 0) return null
    const dates = dailies.map(d => d.date)
    const values = dailies.map(d => d.total_value)
    const drawdowns = dailies.map(d => d.drawdown_pct)
    const gridLeft = isMobile ? 38 : 60
    const gridRight = isMobile ? 10 : 20

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

    // 2026-05-14 visual revamp — palette aligned with the dashboard:
    // equity line stays the dominant visual (sky-400, restrained
    // gradient fill); drawdown bars sit in a smaller secondary grid
    // at lower opacity so they read as context, not foreground.
    // Tooltip integer-rounds money so a 7-decimal float can't leak.
    const EQ_LINE = "#60A5FA"
    const EQ_AREA_TOP = "rgba(96,165,250,0.22)"
    const EQ_AREA_BOTTOM = "rgba(96,165,250,0.02)"
    const DRAWDOWN_AREA = "rgba(248,113,113,0.08)"
    const DRAWDOWN_BAR = "rgba(248,113,113,0.55)"
    const GRID_LINE = "rgba(148,163,184,0.12)"
    const AXIS_LINE = "rgba(148,163,184,0.20)"
    const AXIS_LABEL = "#94A3B8"
    const TOOLTIP_BG = "rgba(15,23,42,0.94)"
    const TOOLTIP_BORDER = "rgba(148,163,184,0.20)"
    const TOOLTIP_TEXT = "#E2E8F0"
    const fmtMoney0 = (v: number) =>
      `$${Math.round(v).toLocaleString("en-US")}`

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: TOOLTIP_BG,
        borderColor: TOOLTIP_BORDER,
        borderWidth: 1,
        textStyle: { color: TOOLTIP_TEXT, fontSize: 12 },
        padding: [8, 10],
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params]
          const head = (arr[0] as { axisValueLabel?: string; name?: string })
          const date = head?.axisValueLabel ?? head?.name ?? ""
          const lines = arr.map((p) => {
            const it = p as { marker?: string; seriesName?: string; value?: unknown }
            const isPct = it.seriesName === "回撤%"
            const v = typeof it.value === "number"
              ? (isPct ? `${it.value.toFixed(2)}%` : fmtMoney0(it.value))
              : String(it.value ?? "")
            return `${it.marker ?? ""}${it.seriesName ?? ""}: <b>${v}</b>`
          })
          return [date, ...lines].join("<br/>")
        },
      },
      grid: [
        { left: gridLeft, right: gridRight, top: 30, height: "55%" },
        { left: gridLeft, right: gridRight, top: "75%", height: "18%" },
      ],
      xAxis: [
        {
          type: "category", data: dates, gridIndex: 0,
          axisLine: { lineStyle: { color: AXIS_LINE } },
          axisLabel: { color: AXIS_LABEL, fontSize: 11 },
          axisTick: { lineStyle: { color: AXIS_LINE } },
        },
        {
          type: "category", data: dates, gridIndex: 1,
          axisLine: { lineStyle: { color: AXIS_LINE } },
          axisLabel: { color: AXIS_LABEL, fontSize: 11 },
          axisTick: { lineStyle: { color: AXIS_LINE } },
        },
      ],
      yAxis: [
        {
          type: "value", gridIndex: 0,
          axisLine: { show: false },
          axisLabel: {
            color: AXIS_LABEL, fontSize: 11,
            formatter: (v: number) => `$${(v/1000).toFixed(0)}k`,
          },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: GRID_LINE } },
        },
        {
          type: "value", gridIndex: 1,
          axisLine: { show: false },
          axisLabel: {
            color: AXIS_LABEL, fontSize: 11,
            formatter: (v: number) => `${v.toFixed(0)}%`,
          },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: GRID_LINE } },
        },
      ],
      series: [
        {
          name: "权益", type: "line", data: values, smooth: true,
          showSymbol: false,
          symbolSize: isMobile ? 4 : 5,
          lineStyle: { color: EQ_LINE, width: 2 },
          itemStyle: { color: EQ_LINE },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: EQ_AREA_TOP },
                { offset: 1, color: EQ_AREA_BOTTOM },
              ],
            },
          },
          markArea: markAreas.length > 0 ? {
            silent: true,
            itemStyle: { color: DRAWDOWN_AREA },
            data: markAreas as any,
          } : undefined,
          z: 3,
        },
        {
          name: "回撤%", type: "bar",
          data: drawdowns, xAxisIndex: 1, yAxisIndex: 1,
          barMaxWidth: isMobile ? 4 : 6,
          itemStyle: {
            color: DRAWDOWN_BAR,
            borderRadius: [0, 0, 2, 2],
          },
          z: 1,
        },
      ],
    }
  }, [dailies, isMobile])

  return (
    <div className="space-y-4">
      {/* paper-trade v1.5: empty + refresh control. When the session
          has an active plan but no daily_stats yet (typical right
          after submitting an analysis on a US holiday or pre-EOD),
          surface "尚未跑 EOD" so the user knows it's not a backend
          regression. */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-xs text-muted-foreground">
          {dailies.length === 0 && hasActivePlan
            ? "尚未跑 EOD — 点击右侧刷新即可补齐到最近交易日"
            : `已记录 ${dailies.length} 个交易日`}
        </div>
        <div className="flex items-center gap-2">
          {eodMsg && (
            <span className="text-xs text-muted-foreground">{eodMsg}</span>
          )}
          <Button
            variant="outline" size="sm"
            onClick={runEod} disabled={eodBusy}
          >
            {eodBusy ? "刷新中…" : "刷新日度数据"}
          </Button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 grid-collapse-mobile">
        <Stat label="当前净值" value={latest ? `$${fmt(latest.total_value)}` : "-"} />
        <Stat label="累计收益" value={latest ? `${latest.cum_pnl_pct.toFixed(2)}%` : "-"}
              delta={latest?.cum_pnl_pct} />
        <Stat label="最大回撤" value={`${maxDrawdown.toFixed(2)}%`} />
        <Stat label="交易天数" value={String(dailies.length)} />
      </div>

      {/* Equity chart — v1.6 mobile-chart-panel wrapper drops the
          panel + ECharts host to a sane mobile height so the chart
          never pushes the trade list below the fold on 320/375. */}
      <Card>
        <CardHeader><CardTitle className="text-sm">权益曲线</CardTitle></CardHeader>
        <CardContent>
          <div className="mobile-chart-panel" data-chart-host>
            {/* 2026-05-14 chart revamp: mobile 320 / desktop 360 so
                the equity line gets enough vertical room to read as
                the primary metric. */}
            <ChartPanel
              option={chartOption}
              height={isMobile ? 320 : 360}
              loading={dailies.length === 0}
            />
          </div>
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
                  <div key={d.date} className="border rounded-lg p-3 min-w-0">
                    <div className="flex justify-between items-center gap-2 min-w-0">
                      <span className="font-mono text-xs shrink-0">{d.date}</span>
                      <span className={cn("font-mono text-sm shrink-0", d.daily_pnl >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        ${fmt(d.daily_pnl)}
                      </span>
                    </div>
                    {/* Three-stat row wraps on 320px so the
                        累计/回撤 numbers don't get clipped. */}
                    <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5 text-xs text-muted-foreground mt-1 min-w-0">
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
          <div className="flex flex-wrap items-center gap-2 mb-1 min-w-0">
            <Badge variant={p.status === "active" ? "default" : "muted"} className="shrink-0">
              {p.rating || "—"}
            </Badge>
            <span className="text-xs font-medium shrink-0">Plan #{p.id}</span>
            {p.status === "active" && <Badge variant="outline" className="text-[10px] shrink-0">当前</Badge>}
            <span className="text-xs text-muted-foreground sm:ml-auto">{p.created_at}</span>
          </div>
          {p.thesis && <p className="text-xs text-muted-foreground mb-1">{p.thesis}</p>}
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
        <div key={e.id} className="flex flex-wrap items-center gap-3 text-sm border-b border-border/50 pb-2 min-w-0">
          <Badge variant={e.signal === "BUY" ? "buy" : e.signal === "SELL" ? "sell" : "muted"} className="text-[10px] shrink-0">
            {e.signal}
          </Badge>
          <span className="text-xs text-muted-foreground shrink-0">{e.created_at}</span>
          <span className="text-xs text-safe text-safe--wrap min-w-0 flex-1">{e.event_type}</span>
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
