/**
 * <OnboardingChecklist> — bottom-floating 4-task progress card.
 *
 * Spec: docs/design/onboarding.md §4.4. Visual: demo `.checklist`.
 *
 *  * 4 tasks one-to-one with the bottom 5 tabs (first 4 of them).
 *  * Auto-hides 600 ms after the 4th task lands + fires a celebratory toast.
 *  * Manual × → permanent dismiss until settings reset.
 *  * Mobile-only.
 */
import { useEffect } from "react"

import { toast } from "@/components/ui/toaster"
import { cn } from "@/lib/utils"

interface OnboardingChecklistProps {
  stepsCompleted: Record<string, boolean>
  onDismiss: () => void
}

interface ChecklistTask {
  readonly id: string
  readonly label: string
  readonly href: string
}

export const TASKS: readonly ChecklistTask[] = [
  { id: "add-holding", label: "添加第一只持仓", href: "/" },
  { id: "first-analysis", label: "完成第一次 AI 分析", href: "/analysis" },
  { id: "first-screen", label: "完成第一次智能选股", href: "/screener-v3" },
  {
    id: "first-paper-plan",
    label: "创建第一笔纸面交易计划",
    href: "/paper-trade",
  },
] as const

export function OnboardingChecklist({
  stepsCompleted,
  onDismiss,
}: OnboardingChecklistProps) {
  const done = TASKS.filter((t) => stepsCompleted[t.id]).length
  const pct = Math.round((done / TASKS.length) * 100)
  const completed = done === TASKS.length

  useEffect(() => {
    if (!completed) return
    const t = setTimeout(() => {
      onDismiss()
      toast.success("🎉 全部任务完成！可在设置中重新开启引导")
    }, 600)
    return () => clearTimeout(t)
  }, [completed, onDismiss])

  return (
    <div
      id="onboarding-checklist"
      className="md:hidden fixed left-3 right-3 bottom-[70px] z-[6] rounded-2xl border border-primary/30 bg-card/96 backdrop-blur shadow-xl p-3"
    >
      <div className="flex items-center justify-between mb-1.5">
        <strong className="text-[13px] text-foreground">🚀 上手任务</strong>
        <button
          type="button"
          className="w-5 h-5 text-muted-foreground hover:text-foreground"
          onClick={onDismiss}
          aria-label="关闭引导"
        >
          ×
        </button>
      </div>
      <div
        className="h-1 bg-white/6 rounded-full overflow-hidden mb-2.5"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full bg-gradient-to-r from-primary to-green-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      {TASKS.map((t, i) => {
        const ok = !!stepsCompleted[t.id]
        return (
          <a
            key={t.id}
            href={ok ? "#" : t.href}
            onClick={(e) => {
              if (ok) e.preventDefault()
            }}
            className={cn(
              "flex items-center gap-2.5 py-1.5 text-xs border-b border-white/4 last:border-0",
              ok
                ? "text-muted-foreground line-through"
                : "cursor-pointer hover:text-primary",
            )}
          >
            <span
              className={cn(
                "w-4 h-4 rounded-full border grid place-items-center text-[10px] shrink-0",
                ok
                  ? "border-green-500 bg-green-500 text-background"
                  : "border-border",
              )}
            >
              {ok ? "✓" : i + 1}
            </span>
            <span className="flex-1">{t.label}</span>
            {!ok && <span className="text-muted-foreground/60">›</span>}
          </a>
        )
      })}
    </div>
  )
}
