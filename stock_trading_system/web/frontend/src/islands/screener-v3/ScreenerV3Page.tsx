import { useMemo, useState } from "react"
import { Play, Zap, Users, Clock, DollarSign, SlidersHorizontal } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Textarea } from "@/components/ui/input"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Avatar } from "@/components/ui/avatar"
import { GURUS } from "@/data/gurus"
import { cn } from "@/lib/utils"

type Mode = "classic" | "agent" | "agent_rt"
const CANDIDATES = [10, 20, 30, 50] as const

export function ScreenerV3Page() {
  const [nl, setNl] = useState("AI 方向，PE<30，负债低")
  const [candidateN, setCandidateN] = useState<number>(20)
  const [mode, setMode] = useState<Mode>("agent")
  const [selected, setSelected] = useState<Set<string>>(
    new Set(["buffett", "graham", "munger", "lynch"])
  )

  const estimate = useMemo(() => {
    if (mode === "classic") {
      return { calls: 0, duration: 3, cost: 0 }
    }
    const gurus = selected.size
    const baseCalls = candidateN * gurus
    const rt = mode === "agent_rt" ? 15 : 0
    const calls = baseCalls + rt
    const duration = Math.round((baseCalls / 10) * 5 + (mode === "agent_rt" ? 45 : 0))
    const cost = calls * 0.02  // ¥0.02/call rough
    return { calls, duration, cost }
  }, [candidateN, selected.size, mode])

  const toggle = (id: string) => {
    setSelected(s => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }
  const selectAll = () => setSelected(new Set(GURUS.map(g => g.id)))
  const selectNone = () => setSelected(new Set())
  const selectRecommended = () => setSelected(new Set(["buffett", "graham", "munger", "lynch"]))

  return (
    <Card className="max-w-4xl">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-[var(--color-accent-blue)]" />
              智能选股 V3 · 大师 Agent
            </CardTitle>
            <p className="text-xs text-[var(--color-text-secondary)] mt-1">
              14 位投资大师深度评估 + Round-table 辩论
            </p>
          </div>
          <Badge variant="blue">BETA</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* 1. NL Query */}
        <Section icon={<SlidersHorizontal className="h-4 w-4" />} title="自然语言描述">
          <Textarea
            rows={2}
            value={nl}
            onChange={e => setNl(e.target.value)}
            placeholder='例如："AI 方向龙头，ROE > 15%，市值 500 亿以上"'
            className="resize-none"
          />
        </Section>

        {/* 2. Market Chip Row */}
        <Section icon={<SlidersHorizontal className="h-4 w-4" />} title="市场">
          <ChipRow>
            <Chip active>美股</Chip>
            <Chip>A 股</Chip>
            <Chip>港股</Chip>
            <Chip size="md">+ 市场偏好</Chip>
          </ChipRow>
        </Section>

        {/* 3. Guru Selector */}
        <Section
          icon={<Users className="h-4 w-4" />}
          title="大师选择"
          subtitle={`${selected.size} / ${GURUS.length} 位已启用`}
          action={
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" onClick={selectAll}>全选</Button>
              <Button variant="ghost" size="sm" onClick={selectRecommended}>推荐 4</Button>
              <Button variant="ghost" size="sm" onClick={selectNone}>全不选</Button>
            </div>
          }
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {GURUS.map(g => {
              const isOn = selected.has(g.id)
              return (
                <label
                  key={g.id}
                  className={cn(
                    "group relative flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all cursor-pointer",
                    isOn
                      ? "bg-[color-mix(in_oklch,var(--color-accent-blue)_6%,transparent)] border-[color-mix(in_oklch,var(--color-accent-blue)_45%,transparent)]"
                      : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-border-bright)]"
                  )}
                >
                  <Checkbox checked={isOn} onCheckedChange={() => toggle(g.id)} />
                  <Avatar initials={g.initials} color={g.color} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold truncate">{g.name}</div>
                    <div className="text-[11px] text-[var(--color-text-muted)] truncate">
                      {g.philosophy}
                    </div>
                  </div>
                  {g.tier === "custom" && (
                    <Badge variant="outline" className="text-[9px]">自建</Badge>
                  )}
                </label>
              )
            })}
          </div>
        </Section>

        {/* 4. Depth Mode */}
        <Section icon={<Zap className="h-4 w-4" />} title="深度模式">
          <RadioGroup value={mode} onValueChange={v => setMode(v as Mode)} className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {[
              { v: "classic" as Mode, t: "经典阈值", d: "秒级完成 · 0 token" },
              { v: "agent" as Mode, t: "Agent 深度", d: "LLM 推理 · 3-5 min" },
              { v: "agent_rt" as Mode, t: "+ 圆桌辩论", d: "Top 5 辩论 · 最深" },
            ].map(opt => (
              <label
                key={opt.v}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-all",
                  mode === opt.v
                    ? "bg-[color-mix(in_oklch,var(--color-accent-blue)_8%,transparent)] border-[var(--color-accent-blue)]"
                    : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-border-bright)]"
                )}
              >
                <RadioGroupItem value={opt.v} className="mt-0.5" />
                <div>
                  <div className="text-sm font-semibold">{opt.t}</div>
                  <div className="text-[11px] text-[var(--color-text-muted)] mt-0.5">{opt.d}</div>
                </div>
              </label>
            ))}
          </RadioGroup>
        </Section>

        {/* 5. Candidate N */}
        <Section icon={<Users className="h-4 w-4" />} title="候选数量">
          <ChipRow>
            {CANDIDATES.map(n => (
              <Chip key={n} active={candidateN === n} onClick={() => setCandidateN(n)}>
                {n} 只
              </Chip>
            ))}
          </ChipRow>
        </Section>

        {/* 6. Cost Estimate */}
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-4">
          <div className="grid grid-cols-3 gap-4">
            <EstimateCell
              icon={<Zap className="h-3.5 w-3.5" />}
              label="LLM 调用"
              value={mode === "classic" ? "—" : `${estimate.calls}`}
            />
            <EstimateCell
              icon={<Clock className="h-3.5 w-3.5" />}
              label="预计时长"
              value={mode === "classic" ? "~3s" : `~${formatDuration(estimate.duration)}`}
            />
            <EstimateCell
              icon={<DollarSign className="h-3.5 w-3.5" />}
              label="成本"
              value={mode === "classic" ? "免费" : `¥${estimate.cost.toFixed(2)}`}
            />
          </div>
        </div>

        {/* 7. Actions */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <Button variant="outline">取消</Button>
          <Button variant="default" size="lg">
            <Play className="h-4 w-4" />
            开始筛选
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Section({
  icon, title, subtitle, action, children,
}: {
  icon: React.ReactNode; title: string; subtitle?: string
  action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[var(--color-text-primary)]">
          <span className="text-[var(--color-text-muted)]">{icon}</span>
          <span className="text-sm font-semibold">{title}</span>
          {subtitle && (
            <span className="text-[11px] text-[var(--color-text-muted)] ml-1">{subtitle}</span>
          )}
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

function EstimateCell({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-muted)]">
        {icon}
        <span>{label}</span>
      </div>
      <div className="font-mono text-lg font-semibold tabular-nums mt-1">{value}</div>
    </div>
  )
}

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}m ${s}s` : `${m} min`
}
