import { useEffect, useState, useMemo, useCallback } from "react"
import {
  TrendingUp, Target, Bell,
  Sparkles, Activity, FileText, BarChart3, RefreshCw,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Chip, ChipRow } from "@/components/ui/chip"
import { ChartPanel } from "@/components/shared/ChartPanel"
import { Sparkline } from "@/components/shared/Sparkline"
import type { EChartsOption } from "@/lib/echarts"
import { apiGet, apiPost } from "@/lib/api"
import { subscribeTaskStream } from "@/lib/socket"
import { cn } from "@/lib/utils"
import { HoldingsSection } from "./HoldingsSection"

interface DashData {
  pnl: { total_value: number; total_pnl: number; total_pnl_pct: number }
  alerts_count: number
  holdings: {
    ticker: string; shares: number
    pnl: number; pnl_pct: number
    market_value: number; avg_cost: number; current_price: number; market: string
  }[]
  history: { date: string; total_value: number; pnl: number }[]
  // v1.16: explicit history-status fields so the equity-curve card can
  // tell "no holdings" apart from "you have holdings but the snapshot
  // table only has 1 row" (the 'click 重新计算' state).
  history_count?: number
  history_first_date?: string | null
  history_last_date?: string | null
  history_status?: "ok" | "insufficient_snapshots"
}

// Result envelope returned by the backfill task. We only inspect a
// handful of fields for the completion-toast surface; the rest is
// kept server-side for the operator log.
interface BackfillResult {
  backfilled?: number
  skipped?: number
  failed?: number
  fallback_prices?: number
  missing_prices?: string[]
  skipped_tickers?: string[]
}

interface TaskRow {
  id: string; type: string; status: string; progress: number; title: string
}

interface AllocItem { ticker: string; value: number; pct: number }

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }
function fmtInt(n: number) { return Math.round(n).toLocaleString("en-US") }
function fmtMoneyInt(n: number) { return `$${fmtInt(n)}` }
function fmtPctInt(n: number) { return `${Math.round(n)}%` }

type Range = "ALL" | "1Y" | "6M" | "3M" | "1M" | "7D"
const RANGE_DAYS: Record<Range, number> = { "ALL": 99999, "1Y": 365, "6M": 180, "3M": 90, "1M": 30, "7D": 7 }
// First-paint window — 90 days covers the default 3M chip plus 1M / 7D
// chips with one cheap query. Other range chips trigger a re-fetch
// against the server window they need (or full history for ALL).
const DEFAULT_HISTORY_DAYS = 90
const FULL_HISTORY = "all"

const rangeToHistoryParam = (r: Range): string =>
  r === "ALL" || r === "1Y" || r === "6M" ? FULL_HISTORY : String(DEFAULT_HISTORY_DAYS)

interface PortfolioSummary {
  total_value: number
  total_pnl: number
  total_pnl_pct: number
  today_pnl: number | null
  today_pnl_pct: number | null
  holdings_count: number
}

export function DashboardPage() {
  const [data, setData] = useState<DashData | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [alloc, setAlloc] = useState<AllocItem[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [transactionsCount, setTransactionsCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState<Range>("3M")
  // Track the server window we already fetched so we don't re-hit
  // /api/dashboard for chips that fit inside the cached series.
  const [loadedHistoryWindow, setLoadedHistoryWindow] = useState<string>(
    String(DEFAULT_HISTORY_DAYS),
  )
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState<string | null>(null)

  // Pull /api/dashboard separately so the ↻ button can refresh it without
  // re-fetching the whole bundle.
  const reloadDashboard = useCallback(async (window: string = loadedHistoryWindow) => {
    const d = await apiGet<DashData>(`/api/dashboard?history_days=${window}`)
      .catch(() => null)
    setData(d)
    setLoadedHistoryWindow(window)
  }, [loadedHistoryWindow])

  // Mobile-ui-v1.3: dashboard now hosts holdings management. After
  // a buy/sell/cost edit we re-pull dashboard (holdings + pnl), the
  // allocation pie, and transactions count so the chips stay accurate.
  const reloadHoldings = useCallback(async () => {
    const [d, a, tx, s] = await Promise.all([
      apiGet<DashData>(`/api/dashboard?history_days=${loadedHistoryWindow}`).catch(() => null),
      apiGet<AllocItem[]>("/api/portfolio/allocation").catch(() => []),
      apiGet<unknown[]>("/api/portfolio/transactions").catch(() => []),
      apiGet<PortfolioSummary>("/api/portfolio/summary").catch(() => null),
    ])
    if (d) setData(d)
    setAlloc(Array.isArray(a) ? a : [])
    setTransactionsCount(Array.isArray(tx) ? tx.length : 0)
    if (s) setSummary(s)
  }, [loadedHistoryWindow])

  useEffect(() => {
    // First-paint default: 90 days (covers the default 3M chip plus the
    // tighter 1M/7D chips with no extra round-trip). The user clicking
    // ALL / 1Y / 6M will trigger a separate fetch for the full series
    // — see the range-effect below.
    Promise.all([
      apiGet<DashData>(`/api/dashboard?history_days=${DEFAULT_HISTORY_DAYS}`).catch(() => null),
      apiGet<TaskRow[]>("/api/tasks?limit=10&offset=0").catch(() => []),
      apiGet<AllocItem[]>("/api/portfolio/allocation").catch(() => []),
      apiGet<unknown[]>("/api/portfolio/transactions").catch(() => []),
      apiGet<PortfolioSummary>("/api/portfolio/summary").catch(() => null),
    ]).then(([d, t, a, tx, s]) => {
      setData(d)
      setTasks(Array.isArray(t) ? t : (t as any)?.tasks || [])
      setAlloc(Array.isArray(a) ? a : [])
      setTransactionsCount(Array.isArray(tx) ? tx.length : 0)
      setSummary(s)
      setLoading(false)
    })
  }, [])

  // Range chip → server window upgrade. We only re-fetch when the chip
  // demands a window we don't already have cached client-side.
  useEffect(() => {
    const need = rangeToHistoryParam(range)
    if (need === loadedHistoryWindow) return
    if (need === FULL_HISTORY && loadedHistoryWindow === FULL_HISTORY) return
    // Going from a shorter cached window to a wider one — reload.
    if (need === FULL_HISTORY ||
        Number(need) > Number(loadedHistoryWindow || "0")) {
      reloadDashboard(need)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range])

  const handleBackfill = async () => {
    setBackfilling(true)
    setBackfillMsg("正在回填历史净值，约 1 分钟…")
    try {
      const res = await apiPost<{ task_id: string }>(
        "/api/portfolio/snapshots/backfill",
        { from: "earliest" },
      )
      const taskId = res.task_id
      // Subscribe to the unified-progress channel; refresh on terminal events.
      const sub = subscribeTaskStream({
        taskIds: [taskId],
        onEvent: async (env) => {
          if (env.event === "task_completed") {
            sub.destroy()
            setBackfillMsg("✓ 回填完成，刷新中…")
            // v1.16: post-backfill, jump straight to the full series.
            // Sticking with the 90-day window means a brand-new
            // multi-year backfill still looks empty until the user
            // clicks ALL — defeats the whole purpose of the button.
            await reloadDashboard(FULL_HISTORY)

            // Surface missing/skipped tickers so the operator can
            // tell "yfinance was unreachable" apart from "TEST1 isn't
            // a real ticker, of course it has no price". The result
            // payload comes through the task event envelope.
            interface CompletedPayload { result?: BackfillResult; missing_prices?: string[]; skipped_tickers?: string[] }
            const payload = env.payload as CompletedPayload
            const r: BackfillResult | undefined =
              payload?.result ?? (payload as BackfillResult)
            const missing = r?.missing_prices ?? []
            const skipped = r?.skipped_tickers ?? []
            const parts: string[] = ["✓ 回填完成"]
            if (typeof r?.backfilled === "number") parts.push(`新增 ${r.backfilled} 天`)
            if (skipped.length > 0) parts.push(`跳过 ${skipped.length} 只无效 ticker：${skipped.slice(0, 3).join(", ")}${skipped.length > 3 ? "…" : ""}`)
            else if (missing.length > 0) parts.push(`${missing.length} 只 ticker 用成本价兜底：${missing.slice(0, 3).join(", ")}${missing.length > 3 ? "…" : ""}`)
            setBackfillMsg(parts.join(" · "))
            setBackfilling(false)
            setTimeout(() => setBackfillMsg(null), skipped.length || missing.length ? 8000 : 2500)
          } else if (env.event === "task_failed") {
            sub.destroy()
            setBackfilling(false)
            setBackfillMsg(`回填失败：${(env.payload as { error_message?: string })?.error_message || "unknown"}`)
            setTimeout(() => setBackfillMsg(null), 5000)
          }
        },
        onStatusChange: () => {},
      })
    } catch (err: unknown) {
      setBackfilling(false)
      setBackfillMsg(err instanceof Error ? `回填失败：${err.message}` : "回填失败")
      setTimeout(() => setBackfillMsg(null), 5000)
    }
  }

  const pnl = data?.pnl || { total_value: 0, total_pnl: 0, total_pnl_pct: 0 }
  const holdings = data?.holdings || []
  const history = data?.history || []
  const runningTasks = tasks.filter(t => t.status === "running")

  // Filter history by range
  const filteredHistory = useMemo(() => {
    const days = RANGE_DAYS[range]
    return history.slice(-days)
  }, [history, range])
  const sparklineValues = useMemo(
    () => history.map(h => h.total_value).filter(Number.isFinite),
    [history],
  )

  // Equity chart option
  const equityOption = useMemo((): EChartsOption | null => {
    if (filteredHistory.length === 0) return null
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "cross",
          // Belt-and-braces rounding: ``valueFormatter`` covers tooltip
          // body, this covers the floating crosshair tag on each axis.
          // Some ECharts builds skip ``valueFormatter`` when a series
          // has its own formatter, so we also set ``yAxis.axisPointer``
          // below — between the three guards a long decimal can't leak.
          label: {
            formatter: (p: { axisDimension?: string; value?: unknown }) => {
              if (p.axisDimension === "y" && typeof p.value === "number") {
                return fmtInt(p.value)
              }
              return String(p.value ?? "")
            },
          },
        },
        // Custom callback (instead of relying on ``valueFormatter`` only)
        // so older ECharts builds + the negative-bar codepath both round.
        formatter: (params: unknown) => {
          const arr = Array.isArray(params) ? params : [params]
          const head = (arr[0] as { axisValueLabel?: string; name?: string })
          const date = head?.axisValueLabel ?? head?.name ?? ""
          const lines = arr.map((p) => {
            const it = p as { marker?: string; seriesName?: string; value?: unknown }
            const v = typeof it.value === "number" ? fmtMoneyInt(it.value)
                    : String(it.value ?? "")
            return `${it.marker ?? ""}${it.seriesName ?? ""}: <b>${v}</b>`
          })
          return [date, ...lines].join("<br/>")
        },
      },
      grid: { left: 60, right: 20, top: 20, bottom: filteredHistory.length > 60 ? 50 : 30 },
      xAxis: { type: "category", data: filteredHistory.map(h => h.date), axisLine: { lineStyle: { color: "#444" } } },
      yAxis: {
        type: "value",
        axisLabel: { formatter: (v: number) => `$${(v/1000).toFixed(0)}k` },
        splitLine: { lineStyle: { color: "#222" } },
        // Last guard: the cross's Y-axis floating tag. Without this
        // formatter ECharts falls back to the raw value string, which
        // is where ``213,322.19902038574`` was leaking from.
        axisPointer: {
          label: {
            formatter: (p: { value?: unknown }) =>
              typeof p.value === "number" ? fmtMoneyInt(p.value) : String(p.value ?? ""),
          },
        },
      },
      dataZoom: filteredHistory.length > 60 ? [{ type: "inside", start: 70, end: 100 }, { type: "slider", height: 20, bottom: 5 }] : [],
      series: [
        {
          name: "净值", type: "line", data: filteredHistory.map(h => h.total_value), smooth: true,
          lineStyle: { color: "#3882ff", width: 2 },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(56,130,255,0.25)" }, { offset: 1, color: "rgba(56,130,255,0)" }] } },
        },
        {
          name: "盈亏", type: "bar", data: filteredHistory.map(h => h.pnl),
          itemStyle: { color: (p: any) => p.value >= 0 ? "#00ff88" : "#ff3860" },
        },
      ],
    }
  }, [filteredHistory])

  // Allocation pie option
  const allocOption = useMemo((): EChartsOption | null => {
    if (alloc.length === 0) return null
    return {
      backgroundColor: "transparent",
      color: ["#3882ff", "#00d4ff", "#a855f7", "#00ff88", "#ff8c00", "#ff3860", "#ffd000", "#bc8cff"],
      tooltip: {
        trigger: "item",
        formatter: (p: any) => {
          const name = p?.name ?? ""
          const value = typeof p?.value === "number" ? fmtMoneyInt(p.value) : p?.value
          // 1 decimal max — never trail a long float into the tooltip.
          const pctRaw = typeof p?.percent === "number" ? p.percent : null
          const pct = pctRaw != null
            ? (pctRaw === Math.round(pctRaw) ? `${pctRaw}%` : `${pctRaw.toFixed(1)}%`)
            : `${p?.percent ?? 0}%`
          return `${name}: ${value} (${pct})`
        },
      },
      // Pull the chart inward + boost label-line lengths so 4-letter
      // tickers like XIACY / META / MSFT have room to render outside
      // the pie without colliding with the card edge or each other.
      // Center stays at 50% horizontally so left and right labels get
      // symmetric breathing room (the previous 42% offset starved the
      // left side and labels got clipped at the card border).
      series: [{
        type: "pie",
        radius: ["32%", "50%"],
        center: ["50%", "55%"],
        avoidLabelOverlap: true,
        minShowLabelAngle: 2,
        data: alloc.map(a => ({ name: a.ticker, value: a.value })),
        label: {
          color: "#e8edf5",
          fontSize: 12,
          fontFamily: "JetBrains Mono, monospace",
          // Ticker only — no percent/amount to keep labels narrow.
          formatter: "{b}",
          // Allow label to flow past the chart edge if needed; the
          // surrounding Card has padding that absorbs ~12px overflow.
          overflow: "none",
        },
        // Longer label lines so the text endpoint sits outside the
        // pie's "shadow" radius — `length` is the radial segment,
        // `length2` is the horizontal jog before the text.
        labelLine: { length: 18, length2: 36, maxSurfaceAngle: 80, smooth: true },
        // ``moveOverlap: "shiftY"`` already on; ``hideOverlap: false``
        // means we never silently drop a ticker (spec rule).
        labelLayout: { hideOverlap: false, moveOverlap: "shiftY" },
        itemStyle: { borderColor: "#111a2e", borderWidth: 2 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.5)" } },
      }],
    }
  }, [alloc])

  if (loading) {
    return <div className="p-8 text-center text-muted-foreground">加载中...</div>
  }

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-6xl mx-auto">
      {/* mobile-ui-v1.3.1 fixup #2: MobileTopbar already shows the
          pageTitle "首页 · 资产与持仓"; on mobile the in-content h1
          duplicates that surface and pushes the account hero below
          the fold. Keep h1 for desktop where the topbar is hidden. */}
      <h1 className="hidden md:block text-xl font-bold">首页</h1>

      {/* mobile-ui-v1.3: account overview — 1 compact card per demo:
          头部 账户总值 + 今日 PnL，下方 总盈亏 / 收益率 / 活跃预警 三栏。
          替换原来 4 个 Stat 卡的整列叠放（grid-collapse-mobile 在 ≤575px
          下会让每张 Stat 卡占满一行）。 */}
      <AccountOverviewCard
        pnl={pnl}
        summary={summary}
        alertsCount={data?.alerts_count ?? 0}
        sparklineValues={sparklineValues}
      />

      {/* Holdings — merged into the home page per mobile-ui-v1.3.
          Default 5 visible, 全部 N expands the full list. */}
      <HoldingsSection
        holdings={holdings}
        transactionsCount={transactionsCount}
        onChange={reloadHoldings}
      />

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Equity chart */}
        <Card className="lg:col-span-2">
          <CardHeader>
            {/* Mobile: title + chips + 重新计算 wrap to three rows
                cleanly; chips themselves scroll horizontally so the
                6 range options never push the button off-screen. */}
            <div className="mobile-card-header">
              <CardTitle className="mc-title text-sm truncate">净值曲线</CardTitle>
              <div className="mc-actions flex items-center gap-2 min-w-0 max-w-full overflow-hidden">
                <ChipRow className="min-w-0">
                  {(["ALL", "1Y", "6M", "3M", "1M", "7D"] as Range[]).map(r => (
                    <Chip key={r} active={range === r} onClick={() => setRange(r)}>{r}</Chip>
                  ))}
                </ChipRow>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleBackfill}
                  disabled={backfilling}
                  title="按交易日重新计算所有历史净值"
                  aria-label="重新计算历史净值"
                  className="h-7 px-2 text-xs shrink-0"
                >
                  <RefreshCw className={cn("h-3.5 w-3.5 mr-1", backfilling && "animate-spin")} />
                  {backfilling ? "回填中" : "重新计算"}
                </Button>
              </div>
            </div>
            {backfillMsg && (
              <div className="text-xs text-muted-foreground mt-1 break-words">{backfillMsg}</div>
            )}
          </CardHeader>
          <CardContent>
            {/* v1.16: explicit "snapshots not enough yet" notice. Old code
                showed a flat 1-point line silently when only today's
                snapshot existed; users assumed the chart was broken.
                Now we keep the chart mounted but layer a hint over it
                that points at the 重新计算 button. */}
            {(data?.history_status === "insufficient_snapshots" ||
              (filteredHistory.length <= 1 && holdings.length > 0)) && (
              <div className="mb-2 rounded border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                历史快照不足（{data?.history_count ?? filteredHistory.length} 个数据点），请点击右上角
                <span className="font-medium text-foreground"> 重新计算 </span>
                生成多日净值曲线。
              </div>
            )}
            <ChartPanel option={equityOption} height={280} loading={filteredHistory.length === 0} />
          </CardContent>
        </Card>

        {/* Allocation pie */}
        <Card>
          <CardHeader><CardTitle className="text-sm">仓位分布</CardTitle></CardHeader>
          <CardContent>
            <ChartPanel option={allocOption} height={280} loading={alloc.length === 0} />
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Running tasks — kept for the operator surface; not a
            cross-page todo aggregator. */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-[var(--color-accent-green)]" />
              <CardTitle>运行中任务</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {runningTasks.length === 0 ? (
              <p className="text-muted-foreground text-sm text-center py-2">无运行中任务</p>
            ) : runningTasks.map(t => (
              <div key={t.id} className="space-y-1.5 cursor-pointer min-w-0"
                   onClick={() => window.location.href = `/tasks/${t.id}`}>
                <div className="flex items-center justify-between gap-2 min-w-0">
                  <span className="text-xs font-medium truncate min-w-0 flex-1">{t.title || t.type}</span>
                  <span className="font-mono text-xs text-muted-foreground shrink-0">{t.progress}%</span>
                </div>
                <Progress value={t.progress} />
              </div>
            ))}
            <div className="text-right">
              <Button variant="ghost" size="sm" onClick={() => window.location.href = "/tasks"}>
                全部任务 →
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Quick actions */}
        <Card>
          <CardHeader><CardTitle>快捷操作</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/reports"}>
              <FileText className="w-3.5 h-3.5 mr-1" /> 生成报告
            </Button>
            <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/analysis"}>
              <Sparkles className="w-3.5 h-3.5 mr-1" /> AI 分析
            </Button>
            <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/alerts"}>
              <Bell className="w-3.5 h-3.5 mr-1" /> 预警中心
            </Button>
            <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/backtest"}>
              <BarChart3 className="w-3.5 h-3.5 mr-1" /> 策略回测
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/* ── Account overview card ────────────────────────────────────
   mobile-ui-v1.3 §4.2: account stats render as ONE compact card
   matching the demo, not four full-width Stat tiles. Layout:
   row 1 — 账户总值 (left) + 今日 PnL (right);
   row 2 — 三栏 metric strip 总盈亏 / 收益率 / 活跃预警. */

export interface AccountOverviewProps {
  pnl: { total_value: number; total_pnl: number; total_pnl_pct: number }
  summary: PortfolioSummary | null
  alertsCount: number
  sparklineValues: number[]
}

// Exported for v1.3.1 R-MUI-21 unit tests; the dashboard page is the
// only production consumer.
export function AccountOverviewCard({
  pnl, summary, alertsCount, sparklineValues,
}: AccountOverviewProps) {
  // /api/portfolio/summary owns today_pnl; fall back to "—" when the
  // backend has no prior snapshot yet (first day of a fresh DB) so we
  // never show a misleading 0.
  const hasToday = summary?.today_pnl != null && summary?.today_pnl_pct != null
  const todayAbs = hasToday ? (summary!.today_pnl as number) : 0
  const todayPct = hasToday ? (summary!.today_pnl_pct as number) : 0
  const todayClass = !hasToday
    ? "text-muted-foreground"
    : todayAbs >= 0
      ? "text-[var(--color-accent-green)]"
      : "text-[var(--color-accent-red)]"
  const totalPnlClass = pnl.total_pnl >= 0
    ? "text-[var(--color-accent-green)]"
    : "text-[var(--color-accent-red)]"
  const returnClass = pnl.total_pnl_pct >= 0
    ? "text-[var(--color-accent-green)]"
    : "text-[var(--color-accent-red)]"

  return (
    <Card className="bg-card/95 ring-1 ring-primary/10 shadow-sm">
      <CardContent className="pt-5 pb-4 px-4 space-y-3">
        {/* mobile-ui-v1.3.1 fixup #2: 账户总值 takes full width as
            the dominant hero number; 今日 PnL sits on its own
            baseline-aligned row below so neither value ever truncates
            at 390px. ``flex-wrap`` + ``ml-auto`` keeps the desktop
            side-by-side feel when the card is wider than ~520px. */}
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0">
          <div className="min-w-0 flex-shrink-0">
            <div className="text-xs text-muted-foreground">账户总值</div>
            <div
              data-account-value=""
              className="font-mono text-2xl font-semibold tabular-nums leading-tight"
            >
              ${fmt(pnl.total_value)}
            </div>
          </div>
          <div className="min-w-0 sm:ml-auto sm:text-right">
            <div className="text-xs text-muted-foreground">今日 PnL</div>
            <div
              data-account-today-pnl=""
              className={cn(
                "font-mono text-sm tabular-nums leading-tight whitespace-nowrap",
                todayClass,
              )}
            >
              {hasToday
                ? `${todayAbs >= 0 ? "+" : ""}$${fmt(todayAbs)} · ${fmtPct(todayPct)}`
                : "—"}
            </div>
          </div>
        </div>
        {sparklineValues.length >= 5 && (
          <div className="-mx-2" data-account-sparkline="">
            <Sparkline
              values={sparklineValues}
              positive={pnl.total_pnl >= 0}
              height={44}
            />
          </div>
        )}
        <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border/40">
          <Metric label="总盈亏"
                  value={`${pnl.total_pnl >= 0 ? "+" : ""}$${fmt(pnl.total_pnl)}`}
                  valueClass={totalPnlClass}
                  icon={<TrendingUp className="h-3 w-3" />} />
          <Metric label="收益率"
                  value={fmtPct(pnl.total_pnl_pct)}
                  valueClass={returnClass}
                  icon={<Target className="h-3 w-3" />} />
          <Metric label="活跃预警"
                  value={String(alertsCount)}
                  valueClass={alertsCount > 0 ? "text-[var(--color-accent-red)]" : "text-foreground"}
                  icon={<Bell className="h-3 w-3" />} />
        </div>
      </CardContent>
    </Card>
  )
}

function Metric({ label, value, valueClass, icon }: {
  label: string; value: string; valueClass?: string; icon?: React.ReactNode
}) {
  return (
    <div className="min-w-0 space-y-0.5">
      <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
        {icon}<span className="truncate">{label}</span>
      </div>
      <div className={cn("font-mono text-sm font-semibold tabular-nums truncate", valueClass)}>
        {value}
      </div>
    </div>
  )
}
