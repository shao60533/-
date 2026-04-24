import { useEffect, useState } from "react"
import {
  TrendingUp, Wallet, Target, Bell,
  Sparkles, CheckCircle2, Clock, Activity,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Stat } from "@/components/ui/stat"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

interface DashData {
  pnl: { total_value: number; total_pnl: number; total_pnl_pct: number }
  alerts_count: number
  holdings: { ticker: string; shares: number; pnl_pct: number; market_value: number }[]
  history: { date: string; total_value: number; pnl: number }[]
}

interface TaskRow {
  id: string; type: string; status: string; progress: number; title: string
}

function fmt(n: number) { return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtPct(n: number) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` }

export function DashboardPage() {
  const [data, setData] = useState<DashData | null>(null)
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      apiGet<DashData>("/api/dashboard").catch(() => null),
      apiGet<TaskRow[]>("/api/tasks?limit=10&offset=0").catch(() => []),
    ]).then(([d, t]) => {
      setData(d)
      setTasks(Array.isArray(t) ? t : (t as any)?.tasks || [])
      setLoading(false)
    })
  }, [])

  if (loading) {
    return <div className="p-8 text-center text-muted-foreground">加载中...</div>
  }

  const pnl = data?.pnl || { total_value: 0, total_pnl: 0, total_pnl_pct: 0 }
  const holdings = data?.holdings || []
  const runningTasks = tasks.filter(t => t.status === "running")

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-6xl mx-auto">
      <h1 className="text-xl font-bold">仪表盘</h1>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
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
                      <span className="text-xs text-muted-foreground">{h.shares} 股</span>
                    </div>
                    <span className={cn("font-mono tabular-nums",
                      h.pnl_pct >= 0 ? "text-green-500" : "text-red-500")}>
                      {fmtPct(h.pnl_pct)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 text-right">
              <Button variant="ghost" size="sm" onClick={() => window.location.href = "/app#portfolio"}>
                管理持仓 →
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Running tasks */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-green-500" />
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

          {/* Quick actions */}
          <Card>
            <CardHeader><CardTitle>快捷操作</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/app#analysis"}>
                <Sparkles className="w-3.5 h-3.5 mr-1" /> AI 分析
              </Button>
              <Button variant="outline" size="sm" className="w-full" onClick={() => window.location.href = "/screener-v3"}>
                <Target className="w-3.5 h-3.5 mr-1" /> 智能选股
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
