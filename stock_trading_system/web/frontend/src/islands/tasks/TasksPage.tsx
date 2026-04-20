import { useEffect, useState } from "react"
import { ListChecks, RefreshCw, Eye, XCircle } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Chip, ChipRow } from "@/components/ui/chip"
import { cn } from "@/lib/utils"
import { apiGet } from "@/lib/api"
import type { Task } from "@/lib/types"

type Scope = "my" | "all"
type Filter = "" | "running" | "pending" | "success" | "failed" | "cancelled"

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  running:   { label: "运行中", variant: "default" },
  pending:   { label: "等待中", variant: "secondary" },
  success:   { label: "已完成", variant: "outline" },
  failed:    { label: "失败",   variant: "destructive" },
  cancelled: { label: "已取消", variant: "secondary" },
}

export function TasksPage() {
  const taskId = window.location.pathname.split("/").pop()
  const isDetail = taskId && taskId !== "tasks-v2"

  const [tasks, setTasks] = useState<Task[]>([])
  const [scope, setScope] = useState<Scope>("my")
  const [filter, setFilter] = useState<Filter>("")
  const [loading, setLoading] = useState(true)

  const loadTasks = async () => {
    setLoading(true)
    try {
      const data = await apiGet<{ tasks: Task[] }>(`/api/tasks?limit=50&offset=0`)
      setTasks(Array.isArray(data) ? data : data.tasks || [])
    } catch { setTasks([]) }
    setLoading(false)
  }

  useEffect(() => { loadTasks() }, [scope])

  const filtered = filter ? tasks.filter(t => t.status === filter) : tasks

  return (
    <div className="min-h-screen bg-background p-4 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <ListChecks className="w-5 h-5" /> 任务中心
        </h1>
        <Button variant="outline" size="sm" onClick={loadTasks}>
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
        <div className="text-center text-muted-foreground py-12">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">暂无任务记录</div>
      ) : (
        <div className="space-y-3">
          {filtered.map(task => (
            <Card key={task.id} className="cursor-pointer hover:border-primary/30 transition-colors"
                  onClick={() => window.location.href = `/tasks-v2/${task.id}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm truncate">{task.title || task.type}</div>
                    <div className="text-xs text-muted-foreground mt-1">{task.created_at}</div>
                  </div>
                  <Badge variant={STATUS_BADGE[task.status]?.variant || "secondary"}>
                    {STATUS_BADGE[task.status]?.label || task.status}
                  </Badge>
                </div>
                {task.status === "running" && task.progress > 0 && (
                  <div className="mt-2 h-1 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full transition-all duration-500"
                         style={{ width: `${task.progress}%` }} />
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
