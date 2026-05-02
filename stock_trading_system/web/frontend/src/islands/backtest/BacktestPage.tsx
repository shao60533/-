import { Suspense, lazy, useEffect, useState, useMemo } from "react"
import { FlaskConical, Play, Clock, ArrowLeft, RotateCw } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Stat } from "@/components/ui/stat"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import type { EChartsOption } from "@/lib/echarts"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { apiGet, apiPost } from "@/lib/api"
import { cn } from "@/lib/utils"

const ChartPanel = lazy(() =>
  import("@/components/shared/ChartPanel").then(m => ({ default: m.ChartPanel })),
)

// v1.7 — strategy contract: ``id`` + ``name`` are canonical. ``label``
// is an alias kept on the wire for one-release migration; the renderer
// reads ``s.name ?? s.label ?? s.id``.
interface Strategy { id: string; name?: string; label?: string; description?: string }
interface TaskSubmitResult { task_id: string; status: string }

/** Wire shape returned by ``/api/tasks/<task_id>/result`` after the
 *  worker writes a backtest_results row. ``TaskStore.load_result`` now
 *  unpacks ``metrics_json`` / ``equity_curve_json`` / ``trades_json``
 *  so the React side reads them directly without a second JSON parse. */
interface BacktestResult {
  ticker: string
  // ``strategy_id`` is canonical. ``strategy`` (legacy) tolerated.
  strategy_id?: string
  strategy?: string
  initial_capital: number
  // Metrics may sit at top-level (worker memory shape) or under
  // ``metrics`` (DB unpack shape). Both are read in displayMetric().
  metrics?: Record<string, number>
  final_value?: number
  total_return?: number
  sharpe_ratio?: number
  max_drawdown?: number
  win_rate?: number
  num_trades?: number
  total_trades?: number  // legacy alias — frontend used this once
  equity_curve: { date: string; value: number }[]
  trades: { date: string; action: string; price: number; shares: number; pnl: number; reason?: string }[]
}

interface TaskResultEnvelope {
  task: { id: string; type: string; status: string; error_message?: string | null }
  result: BacktestResult
}

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }

function getBacktestIdFromUrl(): string | null {
  const m = window.location.pathname.match(/\/backtest(?:-v2)?\/([^/]+)/)
  return m?.[1] ?? null
}

export function BacktestPage() {
  const backtestId = getBacktestIdFromUrl()
  if (backtestId) return <BacktestDetail backtestId={backtestId} />
  return <BacktestForm />
}

/* ── Form ──────────────────────────────────────────────────── */

function BacktestForm() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [ticker, setTicker] = useState("")
  const [strategy, setStrategy] = useState("")
  const [startDate, setStartDate] = useState("2024-01-01")
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [capital, setCapital] = useState("100000")
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<TaskSubmitResult | null>(null)

  useEffect(() => {
    apiGet<Strategy[] | { strategies: Strategy[] }>("/api/backtest/strategies")
      .then(res => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const list = Array.isArray(res) ? res : (res as any).strategies ?? []
        setStrategies(list)
        if (list.length > 0) setStrategy(list[0].id)
      })
      .catch(err => setError(err.message ?? "Failed to load strategies"))
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async () => {
    if (!ticker.trim() || !strategy) return
    setSubmitting(true); setError(null); setSubmitResult(null)
    try {
      // v1.7 — canonical param is ``strategy_id``. The earlier frontend
      // sent ``strategy:`` while the worker read ``strategy_id``,
      // silently routing every run to ``buy_and_hold``. Backend
      // tolerates both keys for one release.
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "backtest",
        params: {
          ticker: ticker.toUpperCase(),
          strategy_id: strategy,
          start_date: startDate,
          end_date: endDate,
          initial_capital: parseFloat(capital),
        },
      })
      setSubmitResult(res)
      // v1.7 — land on the dedicated detail page (which polls
      // /api/tasks/<id>/result) instead of the task-center page that
      // can't render equity curves.
      if (res.task_id) {
        setTimeout(() => { window.location.href = `/backtest/${res.task_id}` }, 600)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally { setSubmitting(false) }
  }

  const strategyLabel = (s: Strategy): string => s.name ?? s.label ?? s.id

  if (loading) return <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4"><Skeleton className="h-8 w-48" /><Skeleton className="h-64" /></div>

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <FlaskConical className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">策略回测</h1>
      </div>

      <Card>
        <CardHeader><CardTitle>配置回测参数</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 grid-collapse-mobile">
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">股票代码</label>
              <Input placeholder="如 AAPL" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">策略</label>
              {strategies.length > 0 ? (
                <Select value={strategy} onValueChange={setStrategy}>
                  <SelectTrigger><SelectValue placeholder="选择策略" /></SelectTrigger>
                  <SelectContent>
                    {strategies.map(s => (
                      <SelectItem key={s.id} value={s.id}>{strategyLabel(s)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : <Input disabled placeholder="无可用策略" />}
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">开始日期</label>
              <Input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">结束日期</label>
              <Input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-sm text-muted-foreground">初始资金 (USD)</label>
              <Input type="number" min="1000" step="1000" value={capital} onChange={e => setCapital(e.target.value)} />
            </div>
          </div>
          <div className="mt-6 flex flex-col gap-3 form-row-mobile">
            <Button onClick={handleSubmit} disabled={submitting || !ticker.trim() || !strategy} className="w-full sm:w-auto">
              {submitting ? <><Clock className="h-4 w-4 mr-1 animate-spin" />提交中...</> : <><Play className="h-4 w-4 mr-1" />开始回测</>}
            </Button>
            {error && <Alert variant="destructive"><AlertTitle>提交失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
            {submitResult && (
              <Alert variant="success">
                <AlertTitle>任务已提交</AlertTitle>
                <AlertDescription>
                  任务 ID: <code className="font-mono">{submitResult.task_id}</code>
                  <a href={`/tasks/${submitResult.task_id}`} className="ml-2 text-[var(--color-accent-blue)] hover:underline">查看进度</a>
                </AlertDescription>
              </Alert>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Result Detail ─────────────────────────────────────────── */

function BacktestDetail({ backtestId }: { backtestId: string }) {
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [pollStatus, setPollStatus] = useState<string>("loading")

  useEffect(() => {
    let cancelled = false
    let timer: number | null = null

    async function tick() {
      try {
        // v1.7 — single source of truth. ``/api/tasks/<id>/result``
        // returns ``{task, result}`` only after the worker finishes;
        // ``TaskStore.load_result`` unpacks the JSON columns from
        // ``backtest_results`` so ``result.equity_curve`` is already
        // structured. Earlier code hit ``/api/tasks/<id>`` which only
        // returns the envelope (no result field) and silently
        // rendered a blank screen.
        const env = await apiGet<TaskResultEnvelope>(`/api/tasks/${backtestId}/result`)
        if (cancelled) return
        setResult(env.result)
        setLoading(false)
        return  // terminal
      } catch {
        // Result not ready — peek at /api/tasks/<id> for the status.
      }
      try {
        const t = await apiGet<{ status: string; error_message?: string }>(`/api/tasks/${backtestId}`)
        if (cancelled) return
        setPollStatus(t.status)
        if (t.status === "failed" || t.status === "cancelled") {
          setError(t.error_message || `任务${t.status === "failed" ? "失败" : "已取消"}`)
          setLoading(false)
          return
        }
        // Still pending/running — poll. 2s feels right for a backtest
        // that typically takes 5-30s.
        timer = window.setTimeout(tick, 2000)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "回测结果未找到")
        setLoading(false)
      }
    }
    tick()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [backtestId])

  if (loading) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Skeleton className="h-8 w-48" />
      <p className="text-xs text-muted-foreground">
        {pollStatus === "running" ? "回测运行中…" :
         pollStatus === "pending" ? "排队中…" : "加载中…"}
      </p>
      <Skeleton className="h-20" />
      <Skeleton className="h-64" />
    </div>
  )

  if (error || !result) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Button variant="ghost" size="sm" onClick={() => window.location.href = "/backtest"}>
        <ArrowLeft className="h-4 w-4 mr-1" />返回
      </Button>
      <Card><CardContent className="py-12 text-center text-muted-foreground">{error || "未找到结果"}</CardContent></Card>
    </div>
  )

  const equityCurve = result.equity_curve || []
  const trades = result.trades || []
  // v1.7 — pull metrics from either the worker's in-memory shape (top
  // level) or the unpacked DB row (under ``metrics``). Both are valid
  // because TaskStore.load_result lifts the keys to top level too.
  const m = result.metrics ?? {}
  const metric = (k: string, fallback: number = 0): number => {
    const v = (result as unknown as Record<string, unknown>)[k]
    if (typeof v === "number" && Number.isFinite(v)) return v
    const v2 = (m as Record<string, unknown>)[k]
    if (typeof v2 === "number" && Number.isFinite(v2)) return v2
    return fallback
  }
  const numTrades = metric("num_trades", 0) || metric("total_trades", trades.length)
  const strategyId = result.strategy_id ?? result.strategy ?? "—"

  const equityOption = useMemo((): EChartsOption | null => {
    if (equityCurve.length === 0) return null
    const dates = equityCurve.map(d => d.date)
    const values = equityCurve.map(d => d.value)

    // Find buy/sell points
    const buyPoints = trades.filter(t => t.action === "BUY").map(t => ({ name: "买", coord: [t.date, t.price], value: t.price }))
    const sellPoints = trades.filter(t => t.action === "SELL").map(t => ({ name: "卖", coord: [t.date, t.price], value: t.price }))

    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 60, right: 20, top: 30, bottom: 30 },
      xAxis: { type: "category", data: dates, axisLine: { lineStyle: { color: "#444" } } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `$${(v/1000).toFixed(0)}k` }, splitLine: { lineStyle: { color: "#222" } } },
      series: [{
        name: "权益", type: "line", data: values, smooth: true,
        lineStyle: { color: "#3882ff", width: 2 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(56,130,255,0.25)" }, { offset: 1, color: "rgba(56,130,255,0)" }] } },
        markPoint: {
          data: [
            ...buyPoints.map(p => ({ ...p, symbol: "triangle", symbolSize: 10, itemStyle: { color: "#00ff88" } })),
            ...sellPoints.map(p => ({ ...p, symbol: "pin", symbolSize: 10, itemStyle: { color: "#ff3860" } })),
          ] as any,
        },
      }],
    }
  }, [equityCurve, trades])

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => window.location.href = "/backtest"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">回测结果</h1>
        {result.ticker && <Badge variant="outline" className="font-mono">{result.ticker}</Badge>}
        {strategyId !== "—" && <Badge variant="muted">{strategyId}</Badge>}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 grid-collapse-mobile">
        <Stat label="Sharpe" value={metric("sharpe_ratio").toFixed(2)} />
        <Stat label="胜率" value={`${(metric("win_rate") * 100).toFixed(1)}%`} />
        <Stat label="总收益" value={fmtPct(metric("total_return") * 100)} delta={metric("total_return") * 100} />
        <Stat label="最大回撤" value={fmtPct(-metric("max_drawdown") * 100)} />
        <Stat label="交易次数" value={String(numTrades)} />
      </div>

      {/* Equity curve */}
      <Card>
        <CardHeader><CardTitle className="text-sm">净值曲线</CardTitle></CardHeader>
        <CardContent>
          <Suspense fallback={<Skeleton className="h-[320px] w-full" />}>
            <ChartPanel option={equityOption} height={320} loading={equityCurve.length === 0} />
          </Suspense>
        </CardContent>
      </Card>

      {/* Trade log */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">交易明细</CardTitle>
            <Button variant="outline" size="sm" onClick={() => window.location.href = `/backtest?from=${backtestId}`}>
              <RotateCw className="h-3.5 w-3.5 mr-1" />再次运行
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <p className="text-center py-8 text-muted-foreground">无交易记录</p>
          ) : (
            <>
              {/* Desktop */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs uppercase">
                      <th className="text-left py-2 px-2">日期</th>
                      <th className="text-left py-2 px-2">动作</th>
                      <th className="text-right py-2 px-2">价格</th>
                      <th className="text-right py-2 px-2">股数</th>
                      <th className="text-right py-2 px-2">PnL</th>
                      <th className="text-left py-2 px-2">理由</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2 px-2 font-mono text-xs">{t.date}</td>
                        <td className="py-2 px-2">
                          <Badge variant={t.action === "BUY" ? "buy" : "sell"}>{t.action}</Badge>
                        </td>
                        <td className="text-right py-2 px-2 font-mono">${fmt(t.price)}</td>
                        <td className="text-right py-2 px-2 font-mono">{t.shares}</td>
                        <td className={cn("text-right py-2 px-2 font-mono",
                          t.pnl >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                          ${fmt(t.pnl || 0)}
                        </td>
                        <td className="py-2 px-2 text-xs text-muted-foreground truncate max-w-[200px]">{t.reason || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Mobile */}
              <div className="md:hidden space-y-2">
                {trades.map((t, i) => (
                  <div key={i} className="border rounded-lg p-3">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <Badge variant={t.action === "BUY" ? "buy" : "sell"}>{t.action}</Badge>
                        <span className="font-mono text-xs">{t.date}</span>
                      </div>
                      <span className={cn("font-mono text-sm", t.pnl >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        ${fmt(t.pnl || 0)}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">{t.shares} 股 @ ${fmt(t.price)}</div>
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
