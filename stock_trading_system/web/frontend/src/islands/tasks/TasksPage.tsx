import { useEffect, useState, useCallback } from "react"
import {
  ListChecks, RefreshCw, XCircle, Eye, Loader2, AlertCircle,
  Trash2, RotateCw, ExternalLink,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import { apiGet, apiPost, apiDel } from "@/lib/api"
import { subscribeTaskStream, type TaskEventEnvelope } from "@/lib/socket"
import { getTaskResultUrl } from "@/lib/tasks"
import { cn } from "@/lib/utils"

interface Task {
  id: string; type: string; status: string; progress: number
  title: string; created_at: string; completed_at: string | null
  result_ref?: string; params_json?: string
}

type StatusFilter = "" | "running" | "pending" | "success" | "failed" | "cancelled"
type TypeFilter = "" | "analysis" | "batch_analysis" | "screen_v3" | "backtest" | "report" | "paper_trade"

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "muted" | "outline" }> = {
  running:   { label: "运行中", variant: "default" },
  pending:   { label: "等待中", variant: "muted" },
  success:   { label: "已完成", variant: "outline" },
  failed:    { label: "失败",   variant: "default" },
  cancelled: { label: "已取消", variant: "muted" },
}

const TYPE_LABELS: Record<string, string> = {
  analysis: "AI 分析", batch_analysis: "批量分析", screen_v3: "选股 V3",
  backtest: "回测", report: "报告", paper_trade: "纸面交易",
  paper_backfill: "回填", screen: "选股",
}

const PAGE_SIZE = 20

export function TasksPage() {
  const path = window.location.pathname
  const taskId = path.startsWith("/tasks/") ? path.split("/tasks/")[1] : null
  if (taskId) return <TaskDetail taskId={taskId} />
  return <TaskList />
}

function TaskList() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("")
  const [scope, setScope] = useState<"my" | "all">("my")
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  const load = useCallback(async (offset = 0, append = false) => {
    if (!append) setLoading(true)
    else setLoadingMore(true)
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE), offset: String(offset), scope,
      })
      if (statusFilter) params.set("status", statusFilter)
      if (typeFilter) params.set("type", typeFilter)
      const data = await apiGet<Record<string, unknown> | Task[]>(`/api/tasks?${params}`)
      const list = Array.isArray(data)
        ? data
        : ((data as any).tasks || (data as any).items || []) as Task[]
      const t = Array.isArray(data)
        ? list.length
        : ((data as any).total ?? list.length)
      if (append) {
        setTasks(prev => [...prev, ...list])
      } else {
        setTasks(list)
      }
      setTotal(t)
    } catch {
      if (!append) setTasks([])
    }
    setLoading(false)
    setLoadingMore(false)
  }, [scope, statusFilter, typeFilter])

  useEffect(() => { load(0) }, [load])

  const handleLoadMore = () => load(tasks.length, true)
  const hasMore = tasks.length < total

  const handleTaskClick = (task: Task) => {
    const url = getTaskResultUrl(task)
    window.location.href = url
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <ListChecks className="w-5 h-5" /> 任务中心
        </h1>
        <Button variant="outline" size="sm" onClick={() => load(0)}>
          <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
        </Button>
      </div>

      {/* Scope tabs */}
      <div className="mb-3">
        <ChipRow>
          <Chip active={scope === "my"} onClick={() => setScope("my")}>我的</Chip>
          <Chip active={scope === "all"} onClick={() => setScope("all")}>全部</Chip>
        </ChipRow>
      </div>

      {/* Status filter */}
      <ChipRow className="mb-2">
        {([["", "全部状态"], ["running", "运行中"], ["pending", "等待中"],
           ["success", "已完成"], ["failed", "失败"], ["cancelled", "已取消"]] as const).map(([v, l]) => (
          <Chip key={v} active={statusFilter === v} onClick={() => setStatusFilter(v as StatusFilter)}>{l}</Chip>
        ))}
      </ChipRow>

      {/* Type filter */}
      <ChipRow className="mb-4">
        {([["", "全部类型"], ["analysis", "AI 分析"], ["batch_analysis", "批量"],
           ["screen_v3", "选股 V3"], ["backtest", "回测"], ["report", "报告"],
           ["paper_trade", "纸面交易"]] as const).map(([v, l]) => (
          <Chip key={v} active={typeFilter === v} onClick={() => setTypeFilter(v as TypeFilter)}>{l}</Chip>
        ))}
      </ChipRow>

      {loading ? (
        <div className="space-y-3">{[1,2,3].map(i => <Skeleton key={i} className="h-16" />)}</div>
      ) : tasks.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">暂无任务记录</div>
      ) : (
        <div className="space-y-2">
          {tasks.map(task => (
            <Card key={task.id} className="cursor-pointer hover:border-primary/30 transition-colors"
                  onClick={() => handleTaskClick(task)}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{task.title || task.type}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-muted-foreground">{task.created_at}</span>
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                        {TYPE_LABELS[task.type] || task.type}
                      </Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={STATUS_BADGE[task.status]?.variant || "muted"}>
                      {STATUS_BADGE[task.status]?.label || task.status}
                    </Badge>
                    {task.status === "success" && (
                      <Button variant="ghost" size="sm" className="h-7 px-2 text-[var(--color-accent-blue)]"
                              onClick={e => { e.stopPropagation(); window.location.href = getTaskResultUrl(task) }}>
                        <ExternalLink className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
                {task.status === "running" && (
                  <div className="mt-2 h-1 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full transition-all"
                         style={{ width: `${task.progress || 0}%` }} />
                  </div>
                )}
              </CardContent>
            </Card>
          ))}

          {/* Load more / footer */}
          <div className="text-center py-4">
            {hasMore ? (
              <Button variant="outline" size="sm" onClick={handleLoadMore} disabled={loadingMore}>
                {loadingMore ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
                加载更多
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">已加载 {tasks.length} / 共 {total}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TaskDetail({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<Task | null>(null)
  const [events, setEvents] = useState<TaskEventEnvelope[]>([])
  const [loading, setLoading] = useState(true)
  const [wsStatus, setWsStatus] = useState<"connecting" | "streaming" | "disconnected">("connecting")

  useEffect(() => {
    apiGet<Task>(`/api/tasks/${taskId}`)
      .then(t => { setTask(t); setLoading(false) })
      .catch(() => setLoading(false))

    const sub = subscribeTaskStream({
      taskIds: [taskId],
      onEvent: (env) => setEvents(prev => [...prev, env]),
      onStatusChange: setWsStatus,
    })
    return () => sub.destroy()
  }, [taskId])

  const handleCancel = async () => {
    try {
      await apiPost(`/api/tasks/${taskId}/cancel`)
      setTask(prev => prev ? { ...prev, status: "cancelled" } : prev)
    } catch {}
  }

  const handleDelete = async () => {
    if (!confirm("确定删除该任务？")) return
    try {
      await apiDel(`/api/tasks/${taskId}`)
      window.location.href = "/tasks"
    } catch {}
  }

  const handleRetry = async () => {
    try {
      await apiPost(`/api/tasks/${taskId}/retry`)
      window.location.reload()
    } catch {}
  }

  if (loading) return <div className="p-6 max-w-4xl mx-auto"><Skeleton className="h-60" /></div>
  if (!task) return (
    <div className="p-6 max-w-3xl mx-auto">
      <Alert variant="destructive"><AlertCircle className="w-4 h-4" /> 任务未找到</Alert>
    </div>
  )

  const doneEvents = events.filter(e =>
    ["guru_unit_done", "batch_analysis_item", "step_done", "agent_stage_done"].includes(e.event)
  )
  const totalN = (events.find(e => (e.payload as any)?.total)?.payload as any)?.total || Math.max(1, doneEvents.length)
  const pct = Math.min(100, Math.round(doneEvents.length / totalN * 100))
  const isTerminal = ["success", "failed", "cancelled"].includes(task.status)

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/tasks"} className="mb-1">← 返回</Button>
          <h1 className="text-lg font-bold">{task.title || task.type}</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-muted-foreground">{task.created_at}</span>
            <Badge variant="outline" className="text-[10px]">{TYPE_LABELS[task.type] || task.type}</Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={STATUS_BADGE[task.status]?.variant || "muted"}>
            {STATUS_BADGE[task.status]?.label || task.status}
          </Badge>
        </div>
      </div>

      {wsStatus === "disconnected" && <Alert>连接中断，自动重连中...</Alert>}

      {/* Progress */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span>已完成 {doneEvents.length}/{totalN}</span>
            <span className="font-mono text-xs">{isTerminal ? 100 : pct}%</span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div className={cn(
              "h-full rounded-full transition-all duration-500",
              task.status === "failed" ? "bg-[var(--color-accent-red)]" : task.status === "cancelled" ? "bg-[var(--color-accent-yellow)]" : "bg-primary",
            )} style={{ width: `${isTerminal ? 100 : pct}%` }} />
          </div>
        </CardContent>
      </Card>

      {/* Events */}
      <Card>
        <CardContent className="p-4">
          <div className="max-h-80 overflow-y-auto space-y-1">
            {events.length === 0 && !isTerminal && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
                <Loader2 className="w-4 h-4 animate-spin" /> 等待事件...
              </div>
            )}
            {events.map((e, i) => {
              const p = (e.payload || {}) as any
              let icon = "📋", title = e.event, meta = ""
              if (e.event === "guru_unit_done") {
                icon = p.signal === "bullish" ? "🟢" : p.signal === "bearish" ? "🔴" : "⚪"
                title = `${p.guru_display || p.guru} × ${p.ticker}`
                meta = `${p.signal} ${Math.round((p.confidence || 0) * 100)}%`
              } else if (e.event === "batch_analysis_item") {
                icon = p.status === "success" ? "✅" : "❌"; title = p.ticker; meta = p.signal || ""
              } else if (e.event === "task_completed") { icon = "✅"; title = "完成" }
              else if (e.event === "task_failed") { icon = "❌"; title = "失败"; meta = p.error || "" }
              else if (e.event === "analysis_pipeline") {
                icon = p.type === "step_done" ? "✅" : "🔄"
                title = p.label || p.type; meta = p.duration_ms ? `${(p.duration_ms/1000).toFixed(1)}s` : ""
              }
              return (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-border/30 last:border-0">
                  <span>{icon} {title}</span>
                  <span className="text-muted-foreground">{meta}</span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Actions */}
      <div className="flex items-center justify-center gap-3">
        {task.status === "success" && (
          <Button onClick={() => window.location.href = getTaskResultUrl(task)}>
            <Eye className="w-4 h-4 mr-1" /> 查看结果
          </Button>
        )}
        {(task.status === "running" || task.status === "pending") && (
          <Button variant="outline" onClick={handleCancel}>
            <XCircle className="w-4 h-4 mr-1" /> 取消
          </Button>
        )}
        {(task.status === "failed" || task.status === "cancelled") && (
          <Button variant="outline" onClick={handleRetry}>
            <RotateCw className="w-4 h-4 mr-1" /> 重试
          </Button>
        )}
        {isTerminal && (
          <Button variant="ghost" className="text-[var(--color-accent-red)]" onClick={handleDelete}>
            <Trash2 className="w-4 h-4 mr-1" /> 删除
          </Button>
        )}
      </div>
    </div>
  )
}
