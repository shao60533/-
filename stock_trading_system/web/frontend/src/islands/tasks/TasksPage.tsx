import { useEffect, useState } from "react"
import { ListChecks, RefreshCw, XCircle, Eye, Loader2, AlertCircle } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert } from "@/components/ui/alert"
import { apiGet, apiPost } from "@/lib/api"
import { subscribeTaskStream, type TaskEventEnvelope } from "@/lib/socket"
import { cn } from "@/lib/utils"

interface Task {
  id: string; type: string; status: string; progress: number
  title: string; created_at: string; completed_at: string | null
}

type Filter = "" | "running" | "pending" | "success" | "failed" | "cancelled"

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  running:   { label: "运行中", variant: "default" },
  pending:   { label: "等待中", variant: "secondary" },
  success:   { label: "已完成", variant: "outline" },
  failed:    { label: "失败",   variant: "destructive" },
  cancelled: { label: "已取消", variant: "secondary" },
}

export function TasksPage() {
  const path = window.location.pathname
  const taskId = path.startsWith("/tasks/") ? path.split("/tasks/")[1] : null
  if (taskId) return <TaskDetail taskId={taskId} />
  return <TaskList />
}

function TaskList() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [filter, setFilter] = useState<Filter>("")
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiGet<Task[] | { tasks: Task[] }>("/api/tasks?limit=50&offset=0")
      setTasks(Array.isArray(data) ? data : (data as any).tasks || [])
    } catch { setTasks([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const filtered = filter ? tasks.filter(t => t.status === filter) : tasks

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <ListChecks className="w-5 h-5" /> 任务中心
        </h1>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
        </Button>
      </div>

      <ChipRow className="mb-4">
        {([["", "全部"], ["running", "运行中"], ["pending", "等待中"],
           ["success", "已完成"], ["failed", "失败"], ["cancelled", "已取消"]] as const).map(([v, l]) => (
          <Chip key={v} active={filter === v} onClick={() => setFilter(v as Filter)}>{l}</Chip>
        ))}
      </ChipRow>

      {loading ? (
        <div className="space-y-3">{[1,2,3].map(i => <Skeleton key={i} className="h-16" />)}</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">暂无任务记录</div>
      ) : (
        <div className="space-y-2">
          {filtered.map(task => (
            <Card key={task.id} className="cursor-pointer hover:border-primary/30 transition-colors"
                  onClick={() => window.location.href = `/tasks/${task.id}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{task.title || task.type}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">{task.created_at}</div>
                  </div>
                  <Badge variant={STATUS_BADGE[task.status]?.variant || "secondary"}>
                    {STATUS_BADGE[task.status]?.label || task.status}
                  </Badge>
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
          <div className="text-xs text-muted-foreground">{task.created_at}</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={STATUS_BADGE[task.status]?.variant || "secondary"}>
            {STATUS_BADGE[task.status]?.label || task.status}
          </Badge>
          {task.status === "running" && (
            <Button variant="outline" size="sm" onClick={handleCancel}>
              <XCircle className="w-3.5 h-3.5 mr-1" /> 停止
            </Button>
          )}
        </div>
      </div>

      {wsStatus === "disconnected" && <Alert>连接中断，自动重连中...</Alert>}

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span>已完成 {doneEvents.length}/{totalN}</span>
            <span className="font-mono text-xs">{isTerminal ? 100 : pct}%</span>
          </div>
          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div className={cn(
              "h-full rounded-full transition-all duration-500",
              task.status === "failed" ? "bg-red-500" : task.status === "cancelled" ? "bg-yellow-500" : "bg-primary",
            )} style={{ width: `${isTerminal ? 100 : pct}%` }} />
          </div>
        </CardContent>
      </Card>

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
              else if (e.event === "task_failed") { icon = "❌"; title = "失败" }
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

      {isTerminal && task.status === "success" && (
        <div className="text-center">
          <Button onClick={() => {
            if (task.type === "screen_v3") window.location.href = "/screener-v3"
            else if (task.type === "analysis") window.location.href = "/app#history"
            else if (task.type === "batch_analysis") window.location.href = "/app#history"
            else window.location.href = "/"
          }}>
            <Eye className="w-4 h-4 mr-1" /> 查看结果
          </Button>
        </div>
      )}
    </div>
  )
}
