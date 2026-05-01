import { useEffect, useState, useRef } from "react"
import { CheckCircle2, XCircle, Loader2, Circle } from "lucide-react"
import { subscribeTaskStream, type TaskEventEnvelope } from "@/lib/socket"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

/** Pipeline stages in TradingAgents execution order */
const STAGES = [
  { id: "market_agent",       label: "技术面" },
  { id: "sentiment_agent",    label: "情绪面" },
  { id: "news_agent",         label: "新闻" },
  { id: "fundamentals_agent", label: "基本面" },
  { id: "bull_researcher",    label: "看多" },
  { id: "bear_researcher",    label: "看空" },
  { id: "judge",              label: "裁判" },
  { id: "risk_manager",       label: "风控" },
  { id: "trader",             label: "决策" },
] as const

type StageStatus = "pending" | "running" | "done" | "failed"

interface PipelineDAGProps {
  taskId: string
  onAllDone?: () => void
}

export function PipelineDAG({ taskId, onAllDone }: PipelineDAGProps) {
  const [stages, setStages] = useState<Record<string, StageStatus>>(() => {
    const init: Record<string, StageStatus> = {}
    for (const s of STAGES) init[s.id] = "pending"
    return init
  })
  const [reasoning, setReasoning] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<string | null>(null)
  const allDoneFired = useRef(false)

  useEffect(() => {
    let currentIdx = 0

    const sub = subscribeTaskStream({
      taskIds: [taskId],
      onEvent: (env: TaskEventEnvelope) => {
        if (env.event === "agent_stage_done" || env.event === "analysis_pipeline") {
          const p = (env.payload || {}) as any
          const stageId = p.stage || p.agent || p.label || ""

          // Match by stage id or by label
          const match = STAGES.find(s =>
            s.id === stageId || s.label === stageId ||
            stageId.toLowerCase().includes(s.id.replace("_agent", ""))
          )

          if (match) {
            setStages(prev => ({ ...prev, [match.id]: "done" }))
            if (p.reasoning || p.summary) {
              setReasoning(prev => ({ ...prev, [match.id]: p.reasoning || p.summary }))
            }
          } else {
            // Sequential fallback: mark next stage as done
            if (currentIdx < STAGES.length) {
              const s = STAGES[currentIdx]
              setStages(prev => ({ ...prev, [s.id]: "done" }))
              currentIdx++
            }
          }

          // Mark next stage as running
          setStages(prev => {
            const updated = { ...prev }
            // find first pending and mark running
            for (const s of STAGES) {
              if (updated[s.id] === "pending") {
                updated[s.id] = "running"
                break
              }
            }
            return updated
          })
        }

        if (env.event === "task_completed") {
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
      },
      onStatusChange: () => {},
    })

    // Mark first stage as running
    setStages(prev => ({ ...prev, [STAGES[0].id]: "running" }))

    // Polling fallback — covers stale page loads + socket drops where no
    // events arrive. When task is already terminal, mark all stages done.
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

    const checkStatus = () => {
      apiGet<{ status?: string }>(`/api/tasks/${taskId}`)
        .then(t => {
          const s = t.status || ""
          if (s === "success") markAllDone()
          else if (s === "failed" || s === "cancelled") {
            setStages(prev => {
              const updated = { ...prev }
              for (const k of Object.keys(updated)) {
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

    return () => { sub.destroy(); clearInterval(poll) }
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
