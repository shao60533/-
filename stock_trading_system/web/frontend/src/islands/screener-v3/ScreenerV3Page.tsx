import { useEffect, useMemo, useState } from "react"
import { Play, Zap, Users, Clock, DollarSign, SlidersHorizontal, ChevronDown, ChevronRight, ArrowLeft } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip, ChipRow } from "@/components/ui/chip"
import { Textarea } from "@/components/ui/input"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Avatar } from "@/components/ui/avatar"
import { Stat } from "@/components/ui/stat"
import { Skeleton } from "@/components/ui/skeleton"
import { GURUS as STATIC_GURUS } from "@/data/gurus"
import { apiGet } from "@/lib/api"
import { cn } from "@/lib/utils"

type Mode = "classic" | "agent" | "agent_rt"
const CANDIDATES = [10, 20, 30, 50] as const

export function ScreenerV3Page() {
  // Check URL for result view
  const params = new URLSearchParams(window.location.search)
  const resultId = params.get("result")

  if (resultId) return <ResultsView resultId={resultId} />
  return <ScreenerForm />
}

/* ── Screener Form (existing, unchanged) ───────────────────── */

function ScreenerForm() {
  const [nl, setNl] = useState("")
  const [candidateN, setCandidateN] = useState<number>(20)
  const [mode, setMode] = useState<Mode>("agent")
  const [selected, setSelected] = useState<Set<string>>(
    new Set(["buffett", "graham", "munger", "lynch"])
  )
  const [gurus, setGurus] = useState(STATIC_GURUS)

  useEffect(() => {
    fetch("/api/screen/v3/gurus", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => {
        const list = d.gurus || d
        if (Array.isArray(list) && list.length > 0) {
          setGurus(list.map((g: any) => ({
            id: g.name, name: g.display_name,
            philosophy: g.philosophy, motto: g.motto,
            color: g.avatar_color, initials: g.avatar_initials,
          })))
        }
      })
      .catch(() => {})
  }, [])

  const [estimate, setEstimate] = useState({ calls: 0, duration: 0, cost: 0 })

  useEffect(() => {
    if (mode === "classic" || selected.size === 0) {
      setEstimate({ calls: 0, duration: 0, cost: 0 })
      return
    }
    const t = setTimeout(async () => {
      try {
        const resp = await fetch("/api/screen/v3/estimate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            candidate_n: candidateN,
            gurus: [...selected],
            with_roundtable: mode === "agent_rt",
          }),
        })
        const data = await resp.json()
        setEstimate({
          calls: data.llm_calls || 0,
          duration: Math.round(data.duration_sec || 0),
          cost: data.cost_cny || 0,
        })
      } catch { /* ignore */ }
    }, 500)
    return () => clearTimeout(t)
  }, [candidateN, selected.size, mode])

  const toggle = (id: string) => {
    setSelected(s => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }
  const selectAll = () => setSelected(new Set(gurus.map(g => g.id)))
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
        <Section icon={<SlidersHorizontal className="h-4 w-4" />} title="自然语言描述">
          <Textarea rows={2} value={nl} onChange={e => setNl(e.target.value)}
            placeholder='例如："AI 方向龙头，ROE > 15%，市值 500 亿以上"' className="resize-none" />
        </Section>

        <Section icon={<SlidersHorizontal className="h-4 w-4" />} title="市场">
          <ChipRow><Chip active>美股</Chip><Chip>A 股</Chip><Chip>港股</Chip></ChipRow>
        </Section>

        <Section icon={<Users className="h-4 w-4" />} title="大师选择"
          subtitle={`${selected.size} / ${gurus.length} 位已启用`}
          action={<div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={selectAll}>全选</Button>
            <Button variant="ghost" size="sm" onClick={selectRecommended}>推荐 4</Button>
            <Button variant="ghost" size="sm" onClick={selectNone}>全不选</Button>
          </div>}>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {gurus.map(g => {
              const isOn = selected.has(g.id)
              return (
                <label key={g.id} className={cn(
                  "group relative flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all cursor-pointer",
                  isOn ? "bg-[color-mix(in_oklch,var(--color-accent-blue)_6%,transparent)] border-[color-mix(in_oklch,var(--color-accent-blue)_45%,transparent)]"
                       : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-border-bright)]"
                )}>
                  <Checkbox checked={isOn} onCheckedChange={() => toggle(g.id)} />
                  <Avatar initials={g.initials} color={g.color} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold truncate">{g.name}</div>
                    <div className="text-[11px] text-[var(--color-text-muted)] truncate">{g.philosophy}</div>
                  </div>
                </label>
              )
            })}
          </div>
        </Section>

        <Section icon={<Zap className="h-4 w-4" />} title="深度模式">
          <RadioGroup value={mode} onValueChange={v => setMode(v as Mode)} className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {[
              { v: "classic" as Mode, t: "经典阈值", d: "秒级完成 · 0 token" },
              { v: "agent" as Mode, t: "Agent 深度", d: "LLM 推理 · 3-5 min" },
              { v: "agent_rt" as Mode, t: "+ 圆桌辩论", d: "Top 5 辩论 · 最深" },
            ].map(opt => (
              <label key={opt.v} className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-all",
                mode === opt.v ? "bg-[color-mix(in_oklch,var(--color-accent-blue)_8%,transparent)] border-[var(--color-accent-blue)]"
                               : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-border-bright)]"
              )}>
                <RadioGroupItem value={opt.v} className="mt-0.5" />
                <div><div className="text-sm font-semibold">{opt.t}</div><div className="text-[11px] text-[var(--color-text-muted)] mt-0.5">{opt.d}</div></div>
              </label>
            ))}
          </RadioGroup>
        </Section>

        <Section icon={<Users className="h-4 w-4" />} title="候选数量">
          <ChipRow>{CANDIDATES.map(n => <Chip key={n} active={candidateN === n} onClick={() => setCandidateN(n)}>{n} 只</Chip>)}</ChipRow>
        </Section>

        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-4">
          <div className="grid grid-cols-3 gap-4 grid-collapse-mobile">
            <EstimateCell icon={<Zap className="h-3.5 w-3.5" />} label="LLM 调用" value={mode === "classic" ? "—" : `${estimate.calls}`} />
            <EstimateCell icon={<Clock className="h-3.5 w-3.5" />} label="预计时长" value={mode === "classic" ? "~3s" : `~${formatDuration(estimate.duration)}`} />
            <EstimateCell icon={<DollarSign className="h-3.5 w-3.5" />} label="成本" value={mode === "classic" ? "免费" : `¥${estimate.cost.toFixed(2)}`} />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => window.location.href = "/"}>取消</Button>
          <Button variant="default" size="lg" onClick={async () => {
            try {
              const resp = await fetch("/api/screen/v3/trigger", {
                method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                body: JSON.stringify({ nl_query: nl, market: "us", candidate_n: candidateN, gurus: [...selected], mode, with_roundtable: mode === "agent_rt" }),
              })
              const data = await resp.json()
              if (data.task_id) window.location.href = `/tasks/${data.task_id}`
            } catch { alert("提交失败") }
          }}>
            <Play className="h-4 w-4" /> 开始筛选
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ── Results View ──────────────────────────────────────────── */

interface ScreenResult {
  id: number
  task_id: string
  candidates: Candidate[]
  roundtable?: { summary: string; consensus: string }
  created_at: string
  params?: Record<string, unknown>
}

interface Candidate {
  ticker: string
  composite_score: number
  signal: string
  guru_scores: Record<string, { signal: string; confidence: number; reasoning?: string; key_metrics?: Record<string, unknown> }>
}

function ResultsView({ resultId }: { resultId: string }) {
  const [result, setResult] = useState<ScreenResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    apiGet<ScreenResult>(`/api/screen/v3/results/${resultId}`)
      .then(r => { setResult(r); setLoading(false) })
      .catch(e => { setError(e.message || "加载失败"); setLoading(false) })
  }, [resultId])

  if (loading) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Skeleton className="h-8 w-48" /><Skeleton className="h-20" /><Skeleton className="h-64" />
    </div>
  )

  if (error || !result) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Button variant="ghost" size="sm" onClick={() => window.location.href = "/screener-v3"}>
        <ArrowLeft className="h-4 w-4 mr-1" />返回
      </Button>
      <Card><CardContent className="py-12 text-center text-muted-foreground">{error || "未找到结果"}</CardContent></Card>
    </div>
  )

  const candidates = result.candidates || []
  const bullish = candidates.filter(c => c.signal?.toLowerCase().includes("bull") || c.signal?.toLowerCase().includes("buy")).length
  const bearish = candidates.filter(c => c.signal?.toLowerCase().includes("bear") || c.signal?.toLowerCase().includes("sell")).length
  const avgScore = candidates.length > 0 ? (candidates.reduce((s, c) => s + (c.composite_score || 0), 0) / candidates.length) : 0

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => window.location.href = "/screener-v3"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">选股结果</h1>
        <Badge variant="muted">{result.created_at?.slice(0, 16)}</Badge>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 grid-collapse-mobile">
        <Stat label="候选数" value={String(candidates.length)} />
        <Stat label="平均分" value={avgScore.toFixed(1)} />
        <Stat label="看多" value={String(bullish)} />
        <Stat label="看空" value={String(bearish)} />
      </div>

      {/* Roundtable */}
      {result.roundtable?.summary && (
        <Card>
          <CardHeader><CardTitle className="text-sm">圆桌辩论结果</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-[var(--color-text-secondary)] whitespace-pre-wrap">{result.roundtable.summary}</p>
            {result.roundtable.consensus && (
              <Badge variant="default" className="mt-2">{result.roundtable.consensus}</Badge>
            )}
          </CardContent>
        </Card>
      )}

      {/* Candidate list */}
      <Card>
        <CardHeader><CardTitle className="text-sm">候选股票排名</CardTitle></CardHeader>
        <CardContent>
          {candidates.length === 0 ? (
            <p className="text-center py-8 text-muted-foreground">无候选结果</p>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden md:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs uppercase">
                      <th className="text-left py-2 px-2">#</th>
                      <th className="text-left py-2 px-2">代码</th>
                      <th className="text-right py-2 px-2">综合分</th>
                      <th className="text-center py-2 px-2">信号</th>
                      <th className="text-right py-2 px-2">大师数</th>
                      <th className="text-right py-2 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c, i) => (
                      <tr key={c.ticker} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2.5 px-2 text-muted-foreground">{i + 1}</td>
                        <td className="py-2.5 px-2 font-mono font-semibold">{c.ticker}</td>
                        <td className="text-right py-2.5 px-2 font-mono">{(c.composite_score || 0).toFixed(1)}</td>
                        <td className="text-center py-2.5 px-2">
                          <Badge variant={signalBadge(c.signal)}>{c.signal || "-"}</Badge>
                        </td>
                        <td className="text-right py-2.5 px-2 text-muted-foreground">{Object.keys(c.guru_scores || {}).length}</td>
                        <td className="text-right py-2.5 px-2">
                          <Button variant="ghost" size="sm" onClick={() => setExpanded(expanded === c.ticker ? null : c.ticker)}>
                            {expanded === c.ticker ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden space-y-2">
                {candidates.map((c, i) => (
                  <div key={c.ticker} className="border rounded-lg p-3 cursor-pointer"
                       onClick={() => setExpanded(expanded === c.ticker ? null : c.ticker)}>
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">#{i + 1}</span>
                        <span className="font-mono font-semibold">{c.ticker}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm">{(c.composite_score || 0).toFixed(1)}</span>
                        <Badge variant={signalBadge(c.signal)}>{c.signal || "-"}</Badge>
                      </div>
                    </div>
                    {expanded === c.ticker && <GuruDetails scores={c.guru_scores} />}
                  </div>
                ))}
              </div>

              {/* Expanded guru details (desktop) */}
              {expanded && (
                <div className="hidden md:block mt-2 border rounded-lg p-4 bg-[var(--color-bg-secondary)]">
                  <div className="text-sm font-semibold mb-2">{expanded} — 大师评分详情</div>
                  <GuruDetails scores={candidates.find(c => c.ticker === expanded)?.guru_scores || {}} />
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function GuruDetails({ scores }: { scores: Record<string, { signal: string; confidence: number; reasoning?: string; key_metrics?: Record<string, unknown> }> }) {
  return (
    <div className="mt-2 space-y-1.5">
      {Object.entries(scores).map(([guru, s]) => (
        <div key={guru} className="flex items-start gap-2 text-xs">
          <Badge variant={signalBadge(s.signal)} className="text-[9px] shrink-0">{s.signal}</Badge>
          <span className="font-medium min-w-[80px]">{guru}</span>
          <span className="font-mono text-muted-foreground">{(s.confidence * 100).toFixed(0)}%</span>
          {s.reasoning && <span className="text-muted-foreground truncate flex-1">{s.reasoning.slice(0, 80)}</span>}
        </div>
      ))}
    </div>
  )
}

function signalBadge(signal: string): "buy" | "sell" | "hold" | "default" {
  const s = (signal || "").toLowerCase()
  if (s.includes("bull") || s.includes("buy")) return "buy"
  if (s.includes("bear") || s.includes("sell")) return "sell"
  if (s.includes("hold") || s.includes("neutral")) return "hold"
  return "default"
}

/* ── Shared sub-components ─────────────────────────────────── */

function Section({ icon, title, subtitle, action, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[var(--color-text-primary)]">
          <span className="text-[var(--color-text-muted)]">{icon}</span>
          <span className="text-sm font-semibold">{title}</span>
          {subtitle && <span className="text-[11px] text-[var(--color-text-muted)] ml-1">{subtitle}</span>}
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
      <div className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-muted)]">{icon}<span>{label}</span></div>
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
