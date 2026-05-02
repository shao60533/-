import { useEffect, useState, useRef } from "react"
import { CheckCircle2, XCircle, Loader2, Circle } from "lucide-react"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

/** Pipeline stage IDs MUST match the backend's ``PIPELINE_STEPS`` first
 * element (see ``stock_trading_system/agents/analyzer.py``). The backend
 * emits events with ``payload.step`` set to one of these IDs and
 * ``payload.type`` describing the lifecycle event. */
const STAGES = [
  { id: "market",       label: "技术面" },
  { id: "social",       label: "情绪面" },
  { id: "news",         label: "新闻" },
  { id: "fundamentals", label: "基本面" },
  { id: "debate",       label: "多空辩论" },
  { id: "risk",         label: "风险评估" },
  { id: "decision",     label: "最终决策" },
] as const

type StageId = typeof STAGES[number]["id"]
type StageStatus = "pending" | "running" | "done" | "failed"

interface AnalysisPipelinePayload {
  type?: "pipeline_start" | "step_start" | "step_done" | "pipeline_done" | "pipeline_error"
  step?: string
  label?: string
  index?: number
  total?: number
  duration_ms?: number
  steps?: Array<{ id: string; status?: StageStatus }>
  reasoning?: string
  summary?: string
}

interface TaskEventEnvelope {
  event: string
  payload?: unknown
}

interface PipelineDAGProps {
  taskId: string
  onAllDone?: () => void
}

function buildInitialStages(): Record<StageId, StageStatus> {
  const init: Record<string, StageStatus> = {}
  for (const s of STAGES) init[s.id] = "pending"
  return init as Record<StageId, StageStatus>
}

export function PipelineDAG({ taskId, onAllDone }: PipelineDAGProps) {
  const [stages, setStages] = useState<Record<StageId, StageStatus>>(buildInitialStages)
  const [reasoning, setReasoning] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<string | null>(null)
  const allDoneFired = useRef(false)

  useEffect(() => {
    const markAllDone = () => {
      setStages(prev => {
        const updated = { ...prev }
        for (const s of STAGES) updated[s.id] = "done"
        return updated
      })
      if (!allDoneFired.current) {
        allDoneFired.current = true
        onAllDone?.()
      }
    }

    const handleEvent = (env: TaskEventEnvelope) => {
        if (env.event === "analysis_pipeline") {
          const p = (env.payload || {}) as AnalysisPipelinePayload
          const evtType = p.type || ""
          const stepId = p.step || ""

          // pipeline_start: initialize ONLY — never advance any node.
          // The backend marks the first step as "running" inside its own
          // step_status snapshot, so we mirror that here without touching
          // any node beyond ``steps[0]``.
          if (evtType === "pipeline_start") {
            setStages(prev => {
              const reset = buildInitialStages()
              if (STAGES.length > 0) reset[STAGES[0].id] = "running"
              return reset
            })
            return
          }

          // step_start: mark this step as running (don't touch others).
          if (evtType === "step_start" && isKnownStage(stepId)) {
            setStages(prev => ({ ...prev, [stepId as StageId]: "running" }))
            return
          }

          // step_done: only this transitions a node to "done". The next
          // pending node (if any) is bumped to "running" so the user sees
          // forward motion.
          if (evtType === "step_done" && isKnownStage(stepId)) {
            setStages(prev => {
              const updated = { ...prev, [stepId as StageId]: "done" }
              for (const s of STAGES) {
                if (updated[s.id] === "pending") {
                  updated[s.id] = "running"
                  break
                }
              }
              return updated
            })
            const note = p.reasoning || p.summary
            if (note) {
              setReasoning(prev => ({ ...prev, [stepId]: note }))
            }
            return
          }

          // pipeline_done / pipeline_error: terminal markers.
          if (evtType === "pipeline_done") {
            markAllDone()
            return
          }
          if (evtType === "pipeline_error") {
            setStages(prev => {
              const updated = { ...prev }
              for (const s of STAGES) {
                if (updated[s.id] === "running") updated[s.id] = "failed"
              }
              return updated
            })
            return
          }
        }

        if (env.event === "task_completed") {
          markAllDone()
        }

        if (env.event === "task_failed") {
          setStages(prev => {
            const updated = { ...prev }
            for (const s of STAGES) {
              if (updated[s.id] === "running") updated[s.id] = "failed"
              else if (updated[s.id] === "pending") break
            }
            return updated
          })
        }
    }

    let disposed = false
    let destroyStream: (() => void) | null = null
    import("@/lib/socket")
      .then(({ subscribeTaskStream }) => {
        if (disposed) return
        const sub = subscribeTaskStream({
          taskIds: [taskId],
          onEvent: handleEvent,
          onStatusChange: () => {},
        })
        destroyStream = () => sub.destroy()
      })
      .catch(() => {
        // Polling fallback below still marks stale/terminal tasks.
      })

    // Polling fallback — covers stale page loads + socket drops where no
    // events arrive. When task is already terminal, mark all stages done.
    const checkStatus = () => {
      apiGet<{ status?: string }>(`/api/tasks/${taskId}`)
        .then(t => {
          const s = t.status || ""
          if (s === "success") markAllDone()
          else if (s === "failed" || s === "cancelled") {
            setStages(prev => {
              const updated = { ...prev }
              for (const k of Object.keys(updated) as StageId[]) {
                if (updated[k] === "running") updated[k] = "failed"
              }
              return updated
            })
            if (!allDoneFired.current) {
              allDoneFired.current = true
              onAllDone?.()
            }
          }
        })
        .catch(() => { /* transient — keep polling */ })
    }
    checkStatus()                              // immediate (covers stale page)
    const poll = setInterval(checkStatus, 5000) // every 5s

    return () => {
      disposed = true
      destroyStream?.()
      clearInterval(poll)
    }
  }, [taskId, onAllDone])

  return (
    <div className="rounded-lg border border-border bg-[var(--color-bg-card)] p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        分析流水线
      </div>

      {/* Desktop: horizontal */}
      <div className="hidden sm:flex items-center gap-1 overflow-x-auto pb-1">
        {STAGES.map((stage, i) => (
          <div key={stage.id} className="flex items-center shrink-0">
            <StageNode
              stage={stage}
              status={stages[stage.id]}
              hasReasoning={!!reasoning[stage.id]}
              expanded={expanded === stage.id}
              onToggle={() => setExpanded(expanded === stage.id ? null : stage.id)}
            />
            {i < STAGES.length - 1 && (
              <div className={cn(
                "w-6 h-px mx-0.5",
                stages[STAGES[i + 1].id] !== "pending"
                  ? "bg-[var(--color-accent-green)]"
                  : "bg-[var(--color-border)]",
              )} />
            )}
          </div>
        ))}
      </div>

      {/* Mobile: vertical */}
      <div className="sm:hidden space-y-1">
        {STAGES.map((stage, i) => (
          <div key={stage.id} className="flex items-center gap-2">
            {i > 0 && (
              <div className={cn(
                "w-px h-3 ml-3.5",
                stages[stage.id] !== "pending" ? "bg-[var(--color-accent-green)]" : "bg-[var(--color-border)]",
              )} />
            )}
            <StageNode
              stage={stage}
              status={stages[stage.id]}
              hasReasoning={!!reasoning[stage.id]}
              expanded={expanded === stage.id}
              onToggle={() => setExpanded(expanded === stage.id ? null : stage.id)}
            />
          </div>
        ))}
      </div>

      {/* Expanded reasoning */}
      {expanded && reasoning[expanded] && (
        <div className="mt-3 rounded-md bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)] whitespace-pre-wrap max-h-40 overflow-y-auto">
          {reasoning[expanded]}
        </div>
      )}
    </div>
  )
}

function isKnownStage(id: string): id is StageId {
  return (STAGES as readonly { id: string }[]).some(s => s.id === id)
}

function StageNode({
  stage,
  status,
  hasReasoning,
  expanded,
  onToggle,
}: {
  stage: { id: string; label: string }
  status: StageStatus
  hasReasoning: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const icon = {
    pending: <Circle className="h-4 w-4 text-muted-foreground" />,
    running: <Loader2 className="h-4 w-4 text-[var(--color-accent-blue)] animate-spin" />,
    done:    <CheckCircle2 className="h-4 w-4 text-[var(--color-accent-green)]" />,
    failed:  <XCircle className="h-4 w-4 text-[var(--color-accent-red)]" />,
  }[status]

  return (
    <button
      onClick={hasReasoning ? onToggle : undefined}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors",
        status === "running" && "bg-[var(--color-accent-blue)]/10",
        status === "done" && "opacity-90",
        status === "pending" && "opacity-50",
        hasReasoning && "cursor-pointer hover:bg-muted/50",
        expanded && "ring-1 ring-[var(--color-accent-blue)]",
      )}
    >
      {icon}
      <span className="whitespace-nowrap">{stage.label}</span>
    </button>
  )
}
