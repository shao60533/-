import { useEffect, useState, useMemo } from "react"
import {
  TrendingUp, Wallet, Target, Bell,
  Sparkles, Activity, FileText, BarChart3, RefreshCw,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Stat } from "@/components/ui/stat"
import { Chip, ChipRow } from "@/components/ui/chip"
import { ChartPanel } from "@/components/shared/ChartPanel"
import type { EChartsOption } from "@/lib/echarts"
import { apiGet, apiPost } from "@/lib/api"
import { subscribeTaskStream } from "@/lib/socket"
import { cn } from "@/lib/utils"

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

type Range = "ALL" | "1Y" | "6M" | "3M" | "1M" | "7D"
const RANGE_DAYS: Record<Range, number> = { "ALL": 99999, "1Y": 365, "6M": 180, "3M": 90, "1M": 30, "7D": 7 }
// First-paint window — 90 days covers the default 3M chip plus 1M / 7D
// chips with one cheap query. Other range chips trigger a re-fetch
// against the server window they need (or full history for ALL).
const DEFAULT_HISTORY_DAYS = 90
const FULL_HISTORY = "all"

const rangeToHistoryParam = (r: Range): string =>
  r === "ALL" || r === "1Y" || r === "6M" ? FULL_HISTORY : String(DEFAULT_HISTORY_DAYS)

export function DashboardPage() {
  const [data, setData] = useState<DashData | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [alloc, setAlloc] = useState<AllocItem[]>([])
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
  const reloadDashboard = async (window: string = loadedHistoryWindow) => {
    const d = await apiGet<DashData>(`/api/dashboard?history_days=${window}`)
      .catch(() => null)
    setData(d)
    setLoadedHistoryWindow(window)
  }

  useEffect(() => {
    // First-paint default: 90 days (covers the default 3M chip plus the
    // tighter 1M/7D chips with no extra round-trip). The user clicking
    // ALL / 1Y / 6M will trigger a separate fetch for the full series
    // — see the range-effect below.
    Promise.all([
      apiGet<DashData>(`/api/dashboard?history_days=${DEFAULT_HISTORY_DAYS}`).catch(() => null),
      apiGet<TaskRow[]>("/api/tasks?limit=10&offset=0").catch(() => []),
      apiGet<AllocItem[]>("/api/portfolio/allocation").catch(() => []),
    ]).then(([d, t, a]) => {
      setData(d)
      setTasks(Array.isArray(t) ? t : (t as any)?.tasks || [])
      setAlloc(Array.isArray(a) ? a : [])
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

  // Equity chart option
  const equityOption = useMemo((): EChartsOption | null => {
    if (filteredHistory.length === 0) return null
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      grid: { left: 60, right: 20, top: 20, bottom: filteredHistory.length > 60 ? 50 : 30 },
      xAxis: { type: "category", data: filteredHistory.map(h => h.date), axisLine: { lineStyle: { color: "#444" } } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `$${(v/1000).toFixed(0)}k` }, splitLine: { lineStyle: { color: "#222" } } },
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
      tooltip: { trigger: "item", formatter: "{b}: {d}%" },
      series: [{
        type: "pie", radius: ["40%", "70%"],
        data: alloc.map(a => ({ name: a.ticker, value: a.value })),
        label: { color: "#e8edf5", fontSize: 12, fontFamily: "JetBrains Mono, monospace" },
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
      <h1 className="text-xl font-bold">仪表盘</h1>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 grid-collapse-mobile">
        <Stat label="账户总值" value={`$${fmt(pnl.total_value)}`}
              icon={<Wallet className="h-4 w-4" />} />
        <Stat label="总盈亏" value={`$${fmt(pnl.total_pnl)}`}
              delta={pnl.total_pnl_pct}
              icon={<TrendingUp className="h-4 w-4" />} />
        <Stat label="收益率" value={fmtPct(pnl.total_pnl_pct)}
              icon={<Target className="h-4 w-4" />} />
        <Stat label="活跃预警" value={String(data?.alerts_count || 0)}
              icon={<Bell className="h-4 w-4" />} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Equity chart */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-sm">净值曲线</CardTitle>
              <div className="flex items-center gap-2">
                <ChipRow>
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
                  className="h-7 px-2 text-xs"
                >
                  <RefreshCw className={cn("h-3.5 w-3.5 mr-1", backfilling && "animate-spin")} />
                  {backfilling ? "回填中" : "重新计算"}
                </Button>
              </div>
            </div>
            {backfillMsg && (
              <div className="text-xs text-muted-foreground mt-1">{backfillMsg}</div>
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Holdings */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>当前持仓</CardTitle>
            <CardDescription>{holdings.length} 只股票</CardDescription>
          </CardHeader>
          <CardContent>
            {holdings.length === 0 ? (
              <p className="text-muted-foreground text-sm py-4 text-center">暂无持仓</p>
            ) : (
              <div className="space-y-2">
                {holdings.map(h => {
                  const pnlAbs = h.pnl ?? 0
                  const pnlClass = pnlAbs > 0
                    ? "text-[var(--color-accent-green)]"
                    : pnlAbs < 0
                      ? "text-[var(--color-accent-red)]"
                      : "text-muted-foreground"
                  return (
                    <div key={h.ticker} className="flex items-center justify-between text-sm border border-border rounded-lg px-4 py-2.5">
                      <div className="flex items-center gap-3">
                        <span className="font-mono font-semibold">{h.ticker}</span>
                        <span className="text-xs text-muted-foreground">{h.market?.toUpperCase()}</span>
                        <span className="text-xs text-muted-foreground">{h.shares} 股</span>
                      </div>
                      <div className="flex items-center gap-4 text-xs">
                        <span className="text-muted-foreground font-mono hidden md:inline">成本 ${fmt(h.avg_cost || 0)}</span>
                        <span className="text-muted-foreground font-mono hidden md:inline">现价 ${fmt(h.current_price || 0)}</span>
                        <span className={cn("font-mono tabular-nums", pnlClass)}>
                          {pnlAbs >= 0 ? "+" : ""}${fmt(pnlAbs)}
                        </span>
                        <span className={cn("font-mono tabular-nums",
                          h.pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                          {fmtPct(h.pnl_pct)}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="mt-3 text-right">
              <Button variant="ghost" size="sm" onClick={() => window.location.href = "/portfolio"}>
                管理持仓 →
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Running tasks + Quick actions */}
        <div className="space-y-4">
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
                <div key={t.id} className="space-y-1.5 cursor-pointer"
                     onClick={() => window.location.href = `/tasks/${t.id}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium truncate">{t.title || t.type}</span>
                    <span className="font-mono text-xs text-muted-foreground">{t.progress}%</span>
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

          {/* Quick actions — 4 buttons */}
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
    </div>
  )
}
