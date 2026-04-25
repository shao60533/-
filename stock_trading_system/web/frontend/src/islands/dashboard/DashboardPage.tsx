import { useEffect, useState, useMemo } from "react"
import {
  TrendingUp, Wallet, Target, Bell,
  Sparkles, Activity, FileText, BarChart3,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Stat } from "@/components/ui/stat"
import { Chip, ChipRow } from "@/components/ui/chip"
import { ChartPanel } from "@/components/shared/ChartPanel"
import type { EChartsOption } from "@/lib/echarts"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

interface DashData {
  pnl: { total_value: number; total_pnl: number; total_pnl_pct: number }
  alerts_count: number
  holdings: { ticker: string; shares: number; pnl_pct: number; market_value: number; avg_cost: number; current_price: number; market: string }[]
  history: { date: string; total_value: number; pnl: number }[]
}

interface TaskRow {
  id: string; type: string; status: string; progress: number; title: string
}

interface AllocItem { ticker: string; value: number; pct: number }

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }

type Range = "7D" | "1M" | "3M" | "1Y"
const RANGE_DAYS: Record<Range, number> = { "7D": 7, "1M": 30, "3M": 90, "1Y": 365 }

export function DashboardPage() {
  const [data, setData] = useState<DashData | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [alloc, setAlloc] = useState<AllocItem[]>([])
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState<Range>("1M")

  useEffect(() => {
    Promise.all([
      apiGet<DashData>("/api/dashboard").catch(() => null),
      apiGet<TaskRow[]>("/api/tasks?limit=10&offset=0").catch(() => []),
      apiGet<AllocItem[]>("/api/portfolio/allocation").catch(() => []),
    ]).then(([d, t, a]) => {
      setData(d)
      setTasks(Array.isArray(t) ? t : (t as any)?.tasks || [])
      setAlloc(Array.isArray(a) ? a : [])
      setLoading(false)
    })
  }, [])

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
      grid: { left: 60, right: 20, top: 20, bottom: 30 },
      xAxis: { type: "category", data: filteredHistory.map(h => h.date), axisLine: { lineStyle: { color: "#444" } } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => `$${(v/1000).toFixed(0)}k` }, splitLine: { lineStyle: { color: "#222" } } },
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
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">净值曲线</CardTitle>
              <ChipRow>
                {(["7D", "1M", "3M", "1Y"] as Range[]).map(r => (
                  <Chip key={r} active={range === r} onClick={() => setRange(r)}>{r}</Chip>
                ))}
              </ChipRow>
            </div>
          </CardHeader>
          <CardContent>
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
                {holdings.map(h => (
                  <div key={h.ticker} className="flex items-center justify-between text-sm border border-border rounded-lg px-4 py-2.5">
                    <div className="flex items-center gap-3">
                      <span className="font-mono font-semibold">{h.ticker}</span>
                      <span className="text-xs text-muted-foreground">{h.market?.toUpperCase()}</span>
                      <span className="text-xs text-muted-foreground">{h.shares} 股</span>
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-muted-foreground font-mono hidden md:inline">成本 ${fmt(h.avg_cost || 0)}</span>
                      <span className="text-muted-foreground font-mono hidden md:inline">现价 ${fmt(h.current_price || 0)}</span>
                      <span className={cn("font-mono tabular-nums",
                        h.pnl_pct >= 0 ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]")}>
                        {fmtPct(h.pnl_pct)}
                      </span>
                    </div>
                  </div>
                ))}
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
