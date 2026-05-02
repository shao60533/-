import { useEffect, useState, useRef } from "react"
import { CheckCircle2, XCircle, Loader2, Circle, MinusCircle } from "lucide-react"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

/**
 * V3-specific screener progress timeline (screener-history v1.1).
 *
 * Replaces the AI-analysis ``<PipelineDAG>`` for ``/screener-v3?task=<id>``.
 * Stages are aligned with ``ScreenerV3Pipeline`` phases — NOT with the
 * analyzer's market/social/news/fundamentals/debate/risk/decision steps.
 *
 * Round-table is conditionally shown only when ``mode === "agent_rt"``;
 * ``agent`` and ``classic`` modes render that node as muted "未启用圆桌"
 * so users in the wrong mode aren't confused by a perpetually-pending
 * stage that will never advance.
 */

type StageId =
  | "parse"
  | "universe"
  | "bundle"
  | "guru"
  | "roundtable"
  | "aggregate"

type StageStatus = "pending" | "running" | "done" | "failed" | "skipped"

interface Stage {
  id: StageId
  label: string
}

const STAGES: Stage[] = [
  { id: "parse",      label: "解析条件" },
  { id: "universe",   label: "构建股票池" },
  { id: "bundle",     label: "拉取行情" },
  { id: "guru",       label: "大师并行评分" },
  { id: "roundtable", label: "圆桌辩论" },
  { id: "aggregate",  label: "生成结果" },
]

interface StagePayload {
  stage?: string
  total?: number
  done?: number
  ticker?: string
  guru_display?: string
  guru?: string
  signals?: number
  results?: number
  count?: number
  source?: string
  tickers?: number | string[]
  progress?: number
}

interface BundleEventPayload {
  ticker?: string
  done?: number
  total?: number
}

interface GuruUnitPayload {
  guru?: string
  guru_display?: string
  ticker?: string
  progress?: number
  total?: number
}

interface RoundtablePayload {
  ticker?: string
  tickers?: string[]
  progress?: number
  total?: number
}

interface TaskEventEnvelope {
  event: string
  payload?: unknown
}

export interface ScreenerV3ProgressProps {
  taskId: string
  /**
   * Which V3 mode the task was launched in. Drives whether the
   * round-table node is rendered as a real stage or as a muted
   * "未启用圆桌" placeholder.
   */
  mode?: "classic" | "agent" | "agent_rt"
  onAllDone?: () => void
}

function buildInitialStages(mode: ScreenerV3ProgressProps["mode"]): Record<StageId, StageStatus> {
  const init: Record<string, StageStatus> = {}
  for (const s of STAGES) init[s.id] = "pending"
  if (mode !== "agent_rt") init.roundtable = "skipped"
  return init as Record<StageId, StageStatus>
}

function isKnownStage(id: string): id is StageId {
  return STAGES.some(s => s.id === id)
}

export function ScreenerV3Progress({ taskId, mode, onAllDone }: ScreenerV3ProgressProps) {
  const [stages, setStages] = useState<Record<StageId, StageStatus>>(() =>
    buildInitialStages(mode),
  )
  const [bundleHint, setBundleHint] = useState<string>("")
  const [guruHint, setGuruHint] = useState<string>("")
  const [guruDone, setGuruDone] = useState<{ done: number; total: number }>(
    { done: 0, total: 0 },
  )
  const [roundtableHint, setRoundtableHint] = useState<string>("")
  const [aggregateHint, setAggregateHint] = useState<string>("")
  const allDoneFired = useRef(false)

  // Reset the skipped/pending state on mode change so a prefill→re-launch
  // with a different mode doesn't leave the round-table cell stuck.
  useEffect(() => {
    setStages(prev => {
      const next = { ...prev }
      if (mode === "agent_rt" && next.roundtable === "skipped") {
        next.roundtable = "pending"
      } else if (mode !== "agent_rt" && next.roundtable === "pending") {
        next.roundtable = "skipped"
      }
      return next
    })
  }, [mode])

  useEffect(() => {
    const markAllDone = () => {
      setStages(prev => {
        const updated: Record<StageId, StageStatus> = { ...prev }
        for (const s of STAGES) {
          if (updated[s.id] === "running" || updated[s.id] === "pending") {
            updated[s.id] = "done"
          }
        }
        return updated
      })
      if (!allDoneFired.current) {
        allDoneFired.current = true
        onAllDone?.()
      }
    }

    const handleEvent = (env: TaskEventEnvelope) => {
        if (env.event === "screen_v3_stage_start") {
          const p = (env.payload || {}) as StagePayload
          const id = p.stage || ""
          if (isKnownStage(id)) {
            setStages(prev => ({ ...prev, [id]: "running" }))
          }
          return
        }
        if (env.event === "screen_v3_stage_done") {
          const p = (env.payload || {}) as StagePayload
          const id = p.stage || ""
          if (isKnownStage(id)) {
            setStages(prev => ({ ...prev, [id]: "done" }))
          }
          if (id === "aggregate") {
            const r = typeof p.results === "number" ? p.results : null
            if (r !== null) setAggregateHint(`${r} 只候选`)
          }
          return
        }

        if (env.event === "bundle_progress") {
          const p = (env.payload || {}) as BundleEventPayload
          const done = typeof p.done === "number" ? p.done : 0
          const total = typeof p.total === "number" ? p.total : 0
          if (total > 0) setBundleHint(`${done}/${total} · ${p.ticker || ""}`)
          // Bundle event arrives before stage_start in some race orders;
          // make sure the stage at least flips to running.
          setStages(prev => prev.bundle === "pending"
            ? { ...prev, bundle: "running" }
            : prev,
          )
          return
        }

        if (env.event === "guru_unit_done") {
          const p = (env.payload || {}) as GuruUnitPayload
          const done = typeof p.progress === "number" ? p.progress : 0
          const total = typeof p.total === "number" ? p.total : 0
          setGuruDone({ done, total })
          const label = `${p.guru_display || p.guru || "?"} · ${p.ticker || "?"}`
          setGuruHint(label)
          setStages(prev => prev.guru === "pending"
            ? { ...prev, guru: "running" }
            : prev,
          )
          return
        }

        if (env.event === "roundtable_start") {
          const p = (env.payload || {}) as RoundtablePayload
          const n = Array.isArray(p.tickers) ? p.tickers.length : 0
          setRoundtableHint(`Top ${n} 准备辩论`)
          setStages(prev => prev.roundtable === "pending" || prev.roundtable === "skipped"
            ? { ...prev, roundtable: "running" }
            : prev,
          )
          return
        }
        if (env.event === "roundtable_done") {
          const p = (env.payload || {}) as RoundtablePayload
          const done = typeof p.progress === "number" ? p.progress : 0
          const total = typeof p.total === "number" ? p.total : 0
          if (total > 0) {
            setRoundtableHint(`${done}/${total} · ${p.ticker || ""}`)
          }
          return
        }

        if (env.event === "aggregate_done") {
          const p = (env.payload || {}) as { results_count?: number }
          if (typeof p.results_count === "number") {
            setAggregateHint(`${p.results_count} 只候选`)
          }
          setStages(prev => ({ ...prev, aggregate: "done" }))
          return
        }

        if (env.event === "task_completed") {
          markAllDone()
          return
        }
        if (env.event === "task_failed") {
          setStages(prev => {
            const updated: Record<StageId, StageStatus> = { ...prev }
            for (const s of STAGES) {
              if (updated[s.id] === "running") updated[s.id] = "failed"
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
        // Polling fallback below still keeps the timeline terminal state correct.
      })

    // Polling fallback — covers stale page loads + socket drops.
    const checkStatus = () => {
      apiGet<{ status?: string }>(`/api/tasks/${taskId}`)
        .then(t => {
          const s = t.status || ""
          if (s === "success") markAllDone()
          else if (s === "failed" || s === "cancelled") {
            setStages(prev => {
              const updated: Record<StageId, StageStatus> = { ...prev }
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
        .catch(() => { /* transient */ })
    }
    checkStatus()
    const poll = setInterval(checkStatus, 5000)

    return () => {
      disposed = true
      destroyStream?.()
      clearInterval(poll)
    }
  }, [taskId, onAllDone])

  const hintFor = (id: StageId): string => {
    if (id === "bundle")     return bundleHint
    if (id === "guru")       return guruDone.total > 0
      ? `${guruDone.done}/${guruDone.total}${guruHint ? ` · ${guruHint}` : ""}`
      : guruHint
    if (id === "roundtable") return roundtableHint
    if (id === "aggregate")  return aggregateHint
    return ""
  }

  return (
    <div className="rounded-lg border border-border bg-[var(--color-bg-card)] p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        选股流水线
      </div>

      {/* Desktop: horizontal */}
      <div className="hidden sm:flex items-center gap-1 overflow-x-auto pb-1">
        {STAGES.map((stage, i) => (
          <div key={stage.id} className="flex items-center shrink-0">
            <StageNode
              stage={stage}
              status={stages[stage.id]}
              hint={hintFor(stage.id)}
            />
            {i < STAGES.length - 1 && (
              <div className={cn(
                "w-6 h-px mx-0.5",
                stages[STAGES[i + 1].id] !== "pending"
                  && stages[STAGES[i + 1].id] !== "skipped"
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
                stages[stage.id] !== "pending"
                  && stages[stage.id] !== "skipped"
                  ? "bg-[var(--color-accent-green)]"
                  : "bg-[var(--color-border)]",
              )} />
            )}
            <StageNode
              stage={stage}
              status={stages[stage.id]}
              hint={hintFor(stage.id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

interface StageNodeProps {
  stage: Stage
  status: StageStatus
  hint?: string
}

function StageNode({ stage, status, hint }: StageNodeProps) {
  const icon = {
    pending: <Circle className="h-4 w-4 text-muted-foreground" />,
    running: <Loader2 className="h-4 w-4 text-[var(--color-accent-blue)] animate-spin" />,
    done:    <CheckCircle2 className="h-4 w-4 text-[var(--color-accent-green)]" />,
    failed:  <XCircle className="h-4 w-4 text-[var(--color-accent-red)]" />,
    skipped: <MinusCircle className="h-4 w-4 text-muted-foreground/50" />,
  }[status]

  const label = status === "skipped" && stage.id === "roundtable"
    ? "未启用圆桌"
    : stage.label

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors",
        status === "running" && "bg-[var(--color-accent-blue)]/10",
        status === "done" && "opacity-90",
        (status === "pending" || status === "skipped") && "opacity-50",
      )}
    >
      {icon}
      <span className="whitespace-nowrap">{label}</span>
      {hint && (
        <span className="text-[10px] text-muted-foreground font-mono ml-1 truncate max-w-[14ch]">
          {hint}
        </span>
      )}
    </div>
  )
}
