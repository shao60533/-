import React, { useEffect, useRef, useState } from "react"
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
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { ScreenerV3Progress } from "@/components/shared/ScreenerV3Progress"
import { GURUS as STATIC_GURUS, type Guru } from "@/data/gurus"
import { apiGet } from "@/lib/api"
// ``subscribeTaskStream`` is dynamic-imported inside the running
// view (and guru matrix) so /screener-v3 home + /screener-v3/history
// don't ship the socket chunk in their entry bundle.
import { cn } from "@/lib/utils"

type Mode = "classic" | "agent" | "agent_rt"
type Market = "us" | "cn" | "hk"
const CANDIDATES = [10, 20, 30, 50] as const

const MARKETS: { value: Market; label: string }[] = [
  { value: "us", label: "美股" },
  { value: "cn", label: "A 股" },
  { value: "hk", label: "港股" },
]

const MODE_LABEL: Record<string, string> = {
  classic: "经典",
  agent: "Agent",
  agent_rt: "Agent + RT",
}
const MARKET_LABEL: Record<string, string> = {
  us: "美股", cn: "A 股", hk: "港股",
}

/* ── Top-level URL dispatcher ──────────────────────────────────
 *
 * Three entry surfaces all share the same Vite bundle:
 *   • /screener-v3                  → home (recent 3 + form)
 *   • /screener-v3/history          → full paginated list
 *   • /screener-v3?task=<id>        → running view (PipelineDAG +
 *                                      guru parallel matrix). Auto-
 *                                      replaceState into ?result= on
 *                                      task_completed.
 *   • /screener-v3?result=<id>      → ResultsView (unchanged from v1.0)
 *   • /screener-v3?prefill=<id>     → home + form pre-populated from
 *                                      a past run (banner explains).
 */
export function ScreenerV3Page() {
  const path = window.location.pathname
  if (path.startsWith("/screener-v3/history")) {
    return <ScreenerHistoryList />
  }
  const params = new URLSearchParams(window.location.search)
  const taskId = params.get("task")
  const resultId = params.get("result")
  const prefillId = params.get("prefill")

  if (taskId) return <ScreenerRunningView taskId={taskId} />
  if (resultId) return <ResultsView resultId={resultId} />
  return <ScreenerHomeView prefillId={prefillId} />
}

function ScreenerHomeView({ prefillId }: { prefillId: string | null }) {
  // analysis-inbox v1.1 + screener-history v1.2 全局规则：
  // 「表单 + 历史」混合主页统一 表单在上（主动作）、历史在下（次要参考）
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <ScreenerForm prefillTaskId={prefillId} />
      <RecentScreensCard />
    </div>
  )
}

/* ── Screener Form ──────────────────────────────────────────────
 *
 * Existing fields + submit logic preserved verbatim. v1.24 only adds
 * an optional ``prefillTaskId`` prop: when set, a one-shot useEffect
 * fetches /api/screen/v3/history/<id> and seeds the controls. Banner
 * above the form makes the prefill visible so the user knows their
 * inputs aren't fresh.
 */
interface ScreenerFormProps {
  prefillTaskId?: string | null
}

function ScreenerForm({ prefillTaskId = null }: ScreenerFormProps) {
  const [nl, setNl] = useState("")
  const [market, setMarket] = useState<Market>("us")
  const [candidateN, setCandidateN] = useState<number>(20)
  const [mode, setMode] = useState<Mode>("agent")
  const [selected, setSelected] = useState<Set<string>>(
    new Set(["buffett", "graham", "munger", "lynch"])
  )
  const [gurus, setGurus] = useState<Guru[]>(STATIC_GURUS)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [prefillBanner, setPrefillBanner] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/screen/v3/gurus", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => {
        const list = d.gurus || d
        if (Array.isArray(list) && list.length > 0) {
          setGurus(list.map((g: any): Guru => ({
            id: g.name,
            name: g.display_name,
            philosophy: g.philosophy,
            color: g.avatar_color,
            initials: g.avatar_initials,
            // Backend /api/screen/v3/gurus omits principles + tier — fall
            // back to safe defaults so Guru[] stays type-safe.
            principles: Array.isArray(g.principles) ? g.principles : [],
            tier: (g.tier as Guru["tier"]) ?? "core",
          })))
        }
      })
      .catch(() => {})
  }, [])

  /* Prefill from a past run. Effect waits for the live ``gurus`` list
   * to load so we can intersect the historical guru ids against the
   * currently-registered set — gurus that have been retired since the
   * source run are silently dropped, otherwise the form would have a
   * checkbox that points at nothing. */
  useEffect(() => {
    if (!prefillTaskId) return
    if (!gurus.length) return
    apiGet<HistoryRow>(`/api/screen/v3/history/${prefillTaskId}`)
      .then(r => {
        if (!r?.params) return
        setNl(r.params.nl_query || "")
        setMarket((r.params.market || "us") as Market)
        setCandidateN(Number(r.params.candidate_n) || 20)
        setMode(
          r.params.with_roundtable ? "agent_rt"
          : r.params.mode === "classic" ? "classic"
          : "agent",
        )
        const valid = new Set(gurus.map(g => g.id))
        const want = new Set((r.params.gurus || []).filter(g => valid.has(g)))
        if (want.size > 0) setSelected(want)
        setPrefillBanner(
          `已从 ${fmtRelative(r.created_at)} 的运行复制配置，可修改后重跑`,
        )
      })
      .catch(() => {
        // Silently no-op on prefill miss — user can still fill fresh.
      })
  // gurus.length is the readiness signal; keep effect single-shot per id.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillTaskId, gurus.length])

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
            market,
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
  }, [market, candidateN, selected.size, mode])

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
    <div className="max-w-4xl space-y-3">
      {prefillBanner && (
        <Alert variant="default">
          <AlertTitle>已复制配置</AlertTitle>
          <AlertDescription>{prefillBanner}</AlertDescription>
        </Alert>
      )}
    <Card>
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
          <ChipRow>
            {MARKETS.map(m => (
              <Chip key={m.value}
                    active={market === m.value}
                    onClick={() => setMarket(m.value)}>
                {m.label}
              </Chip>
            ))}
          </ChipRow>
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

        <div className="flex flex-col gap-2 pt-2 items-end">
          {selected.size === 0 && (
            <p className="text-xs text-[var(--color-accent-red)]">至少选择 1 位大师</p>
          )}
          {submitError && (
            <p className="text-xs text-[var(--color-accent-red)]">{submitError}</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" onClick={() => window.location.href = "/"}>取消</Button>
            <Button
              variant="default" size="lg"
              disabled={selected.size === 0 || submitting}
              onClick={async () => {
                if (selected.size === 0) {
                  setSubmitError("至少选择 1 位大师")
                  return
                }
                setSubmitting(true)
                setSubmitError(null)
                try {
                  const resp = await fetch("/api/screen/v3/trigger", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({
                      nl_query: nl, market,
                      candidate_n: candidateN,
                      gurus: [...selected], mode,
                      with_roundtable: mode === "agent_rt",
                    }),
                  })
                  const data = await resp.json()
                  if (resp.ok && data.task_id) {
                    // v1.24: bounce back into the screener so the user
                    // sees pipeline + guru parallel progress in the same
                    // surface, not /tasks/<id> (the original "为什么只能
                    // 从任务中心查" complaint root cause).
                    window.location.href = `/screener-v3?task=${data.task_id}`
                    return
                  }
                  setSubmitError(data.message || data.error || "提交失败")
                } catch {
                  setSubmitError("网络错误，请重试")
                } finally {
                  setSubmitting(false)
                }
              }}>
              <Play className="h-4 w-4" /> 开始筛选
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
    </div>
  )
}

/* ── Results View ──────────────────────────────────────────── */

// v1.2: run-mode banner metadata. All fields tolerated as missing for
// pre-v1.2 result rows (DTO emits zeros / empty list rather than null).
interface RunMetadata {
  mode: string
  llm_calls: number
  cache_hits: number
  cache_hit_pct: number
  duration_sec: number
  gurus_used: string[]
  candidates_count: number
  roundtable_enabled: boolean
}

interface Votes { bullish: number; bearish: number; neutral: number; total: number }

interface Argument { guru: string; confidence: number; snippet: string }

interface RoundtableItem {
  ticker: string
  consensus: string[]
  dissent: string[]
  split: boolean
  debate_snippets: string[]
}

interface ScreenResult {
  id: number
  task_id: string
  // Backend canonical key is ``candidates``; tolerate older / stale
  // worker payloads that wrote ``results`` instead so a bad cache miss
  // doesn't render an empty page.
  candidates?: Candidate[]
  results?: Candidate[]
  // v1.2: roundtable arrives as ``{items: [{ticker, ...}]}`` envelope.
  // Legacy ``{summary, consensus}`` shape still tolerated.
  roundtable?: { items?: RoundtableItem[]; summary?: string; consensus?: string } | null
  created_at: string
  params?: Record<string, unknown>
  run_metadata?: RunMetadata
}

interface GuruSubAnalysis {
  name: string
  // ``score`` may be number-encoded as string from older payloads. We
  // narrow at usage time, not at the type boundary.
  score: number | string
  details?: string
}

interface GuruScore {
  signal: string
  confidence: number
  reasoning?: string
  key_metrics?: Record<string, unknown>
  // v1.4 — sub_analyses now ships through ``guru_signals[].sub_analyses``
  // so the expanded card can show ``theme_fit`` as a small badge and
  // pull the lowest-scored dimension as the "risk" line.
  sub_analyses?: GuruSubAnalysis[]
  total_score?: number
  // v1.0 GuruSignal extras the expanded-row card surfaces.
  tier?: string
  philosophy?: string
}

// Backend normalises older worker payloads into the canonical shape, but
// we keep the tolerant aliases below so a stale worker still renders.
interface Candidate {
  ticker: string
  composite_score?: number
  final_score?: number
  // Server is supposed to backfill this with _derive_candidate_signal;
  // keep nullable so an older API shape (or a hard-cached stale JSON
  // payload) still type-checks.
  signal?: string | null
  guru_scores?: Record<string, GuruScore>
  guru_signals?: Array<{ guru: string } & GuruScore>
  // v1.2 additive fields emitted by ``ScreenerV3Pipeline._aggregate``.
  votes?: Votes
  consensus?: string
  confidence_range?: { min: number; max: number; avg: number }
  top_bull_argument?: Argument | null
  top_bear_argument?: Argument | null
  roundtable?: RoundtableItem | null
}

// ── v1.2 display helpers ─────────────────────────────────────────────────

function consensusBadge(c: string): "buy" | "sell" | "hold" | "default" {
  if (c === "unanimous") return "buy"
  if (c === "majority") return "hold"
  if (c === "split") return "sell"
  return "default"
}

function consensusLabel(c: string): string {
  return c === "unanimous" ? "全员共识"
       : c === "majority" ? "多数派"
       : c === "split" ? "对峙"
       : "—"
}

function fmtDuration(sec: number): string {
  if (!sec) return "—"
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function tierLabel(tier?: string): string {
  return tier === "core" ? "核心"
       : tier === "advanced" ? "进阶"
       : tier === "classic" ? "经典"
       : ""
}

function modeLabel(mode?: string): string {
  return mode === "agent_rt" ? "Agent + 圆桌"
       : mode === "agent" ? "Agent (无圆桌)"
       : mode === "classic" ? "经典阈值"
       : "Agent"
}

/** Read a numeric fundamentals field; tolerates strings ("28.5") and
 *  the akshare "—" / "N/A" sentinels by returning ``null``. */
function fundNum(fund: Record<string, unknown> | null | undefined,
                  key: string): number | null {
  if (!fund) return null
  const raw = fund[key]
  if (typeof raw === "number" && Number.isFinite(raw)) return raw
  if (typeof raw === "string") {
    const n = Number(raw)
    if (Number.isFinite(n)) return n
  }
  return null
}

const fmtNum = (v: number | null | undefined, d = 1) =>
  v != null && Number.isFinite(v) ? v.toFixed(d) : "—"
const fmtPct = (v: number | null | undefined) =>
  v != null && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "—"
const fmtPrice = (v: number | null | undefined) =>
  v != null && Number.isFinite(v) ? `$${v.toFixed(2)}` : "—"

const candidateScore = (c: Candidate): number =>
  (c.composite_score ?? c.final_score ?? 0)

const candidateGuruScores = (c: Candidate): Record<string, GuruScore> => {
  if (c.guru_scores && Object.keys(c.guru_scores).length > 0) return c.guru_scores
  if (Array.isArray(c.guru_signals)) {
    const out: Record<string, GuruScore> = {}
    for (const s of c.guru_signals) {
      if (s && s.guru) out[s.guru] = s
    }
    return out
  }
  return {}
}

/**
 * Derive a non-empty signal for a candidate. Mirror of the backend
 * ``_derive_candidate_signal`` so a stale cached response (server
 * pre-v1.16) still produces useful 看多/看空 counts.
 *
 *   1. existing ``signal`` if non-empty
 *   2. majority among guru votes
 *   3. composite_score band: >=65 bullish, <=40 bearish, else neutral
 *   4. "neutral" default
 */
const candidateSignal = (c: Candidate): string => {
  const explicit = (c.signal || "").trim()
  if (explicit) return explicit
  const gurus = candidateGuruScores(c)
  let bullish = 0, bearish = 0
  for (const g of Object.values(gurus)) {
    const s = (g?.signal || "").toLowerCase()
    if (s.includes("bull") || s.includes("buy")) bullish++
    else if (s.includes("bear") || s.includes("sell")) bearish++
  }
  if (bullish > bearish) return "bullish"
  if (bearish > bullish) return "bearish"
  const sc = candidateScore(c)
  if (sc >= 65) return "bullish"
  if (sc <= 40 && sc > 0) return "bearish"
  return "neutral"
}

function ResultsView({ resultId }: { resultId: string }) {
  const [result, setResult] = useState<ScreenResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)
  // v1.2: lazy-load /api/fundamentals/<ticker> per row. Cache in state
  // so re-renders don't refetch; ``fundLoading`` ref prevents the same
  // ticker firing twice while the network call is in flight.
  const [funds, setFunds] = useState<Record<string, Record<string, unknown> | null>>({})
  const fundLoading = useRef<Set<string>>(new Set())

  useEffect(() => {
    apiGet<ScreenResult>(`/api/screen/v3/results/${resultId}`)
      .then(r => { setResult(r); setLoading(false) })
      .catch(e => { setError(e.message || "加载失败"); setLoading(false) })
  }, [resultId])

  // Trigger one fundamentals fetch per ticker once the result lands.
  // /api/fundamentals/<ticker> is backed by the v1.6 LocalCache (30s
  // TTL) so this stays cheap on re-mount.
  useEffect(() => {
    if (!result) return
    const cs = result.candidates || result.results || []
    for (const c of cs) {
      if (funds[c.ticker] !== undefined) continue
      if (fundLoading.current.has(c.ticker)) continue
      fundLoading.current.add(c.ticker)
      apiGet<Record<string, unknown>>(`/api/fundamentals/${c.ticker}`)
        .then(d => setFunds(prev => ({ ...prev, [c.ticker]: d })))
        .catch(() => setFunds(prev => ({ ...prev, [c.ticker]: null })))
    }
    // Only re-fire when the result identity changes — funds map updates
    // shouldn't retrigger the loop (that would race the loading set).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.task_id])

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

  const candidates = result.candidates || result.results || []
  // v1.2 verdict counts ignore "split" so the "对峙" rows surface in
  // their own column rather than masquerading as bull/bear.
  const bullish = candidates.filter(c => {
    const s = candidateSignal(c).toLowerCase()
    return (s === "bullish" || s === "buy") && c.consensus !== "split"
  }).length
  const bearish = candidates.filter(c => {
    const s = candidateSignal(c).toLowerCase()
    return (s === "bearish" || s === "sell") && c.consensus !== "split"
  }).length
  const neutral = candidates.length - bullish - bearish
  const consensusRate = candidates.length > 0
    ? Math.round(
        candidates.filter(
          c => c.consensus === "unanimous" || c.consensus === "majority",
        ).length / candidates.length * 100,
      )
    : 0
  const avgScore = candidates.length > 0
    ? (candidates.reduce((s, c) => s + candidateScore(c), 0) / candidates.length)
    : 0

  // Roundtable envelope can be a v1.2 ``{items: [...]}`` shape OR a
  // legacy ``{summary, consensus}`` shape. Prefer items; show legacy
  // only if items is missing AND there's a summary blob.
  const roundtableItems: RoundtableItem[] | null =
    Array.isArray(result.roundtable?.items) ? result.roundtable!.items! :
    null

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => window.location.href = "/screener-v3"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">选股结果</h1>
        <Badge variant="muted">{result.created_at?.slice(0, 16)}</Badge>
      </div>

      {/* v1.2 — 6 KPI columns. Pre-v1.2 rows without ``consensus`` /
          ``votes`` still light up bullish/bearish/neutral via signal,
          but consensus_rate falls back to 0 (acceptable degraded UX). */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 grid-collapse-mobile">
        <Stat label="候选数" value={String(candidates.length)} />
        <Stat label="平均分" value={avgScore.toFixed(1)} />
        <Stat label="看多" value={String(bullish)} />
        <Stat label="看空" value={String(bearish)} />
        <Stat label="中性" value={String(neutral)} />
        <Stat label="共识率" value={`${consensusRate}%`} />
      </div>

      {/* v1.2 — run-mode banner. Hidden for legacy rows that have no
          metadata (DTO emits zeros + empty list, which we read as
          "nothing meaningful to show"). */}
      {result.run_metadata && result.run_metadata.gurus_used.length + result.run_metadata.llm_calls > 0 && (
        <Card>
          <CardContent className="py-3 flex flex-wrap items-center gap-3 text-xs">
            <Badge variant="default">⚡ {modeLabel(result.run_metadata.mode)}</Badge>
            <span>{result.run_metadata.gurus_used.length} 大师</span>
            {result.run_metadata.gurus_used.length > 0 && (
              <div className="flex -space-x-1">
                {result.run_metadata.gurus_used.slice(0, 6).map(g => (
                  <Avatar key={g} initials={g.slice(0, 2).toUpperCase()} size="sm"
                          className="border-2 border-background" />
                ))}
              </div>
            )}
            <span className="text-muted-foreground">·</span>
            <span>{result.run_metadata.llm_calls} LLM call</span>
            <span className="text-muted-foreground">·</span>
            <span>命中缓存 {result.run_metadata.cache_hit_pct}%</span>
            <span className="text-muted-foreground">·</span>
            <span>耗时 {fmtDuration(result.run_metadata.duration_sec)}</span>
            {!result.run_metadata.roundtable_enabled && (
              <Badge variant="muted" className="ml-auto">无圆桌</Badge>
            )}
          </CardContent>
        </Card>
      )}

      {/* v1.2 — Top-5 圆桌辩论 grid (one card per ticker). */}
      {roundtableItems && roundtableItems.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Top 5 圆桌辩论</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {roundtableItems.map(rt => (
                <Card key={rt.ticker}
                      className={cn(
                        "border",
                        rt.split ? "border-orange-500/40" : "border-emerald-500/40",
                      )}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="font-mono text-base">{rt.ticker}</CardTitle>
                      <Badge variant={rt.split ? "sell" : "buy"}>
                        {rt.split ? "CONTESTED" : "CONSENSUS"}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      共识 {rt.consensus?.length ?? 0} 人
                      {rt.dissent && rt.dissent.length > 0 && (
                        <> · 异议 {rt.dissent.length} 人</>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {(rt.debate_snippets || []).map((line, i) => {
                      const isBull = line.startsWith("🟢")
                      const isBear = line.startsWith("🔴")
                      const isJudge = line.startsWith("⚖️")
                      return (
                        <div key={i} className={cn(
                          "text-xs leading-relaxed pl-2 border-l-2",
                          isBull ? "border-emerald-500/50"
                          : isBear ? "border-red-500/50"
                          : isJudge ? "border-primary"
                          : "border-zinc-500/30",
                        )}>{line}</div>
                      )
                    })}
                  </CardContent>
                </Card>
              ))}
            </div>
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
              {/* Desktop table — v1.2 columns: votes分布 + 共识度 + 现价 + PE */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-muted-foreground text-xs uppercase">
                      <th className="text-left py-2 px-2">#</th>
                      <th className="text-left py-2 px-2">代码</th>
                      <th className="text-right py-2 px-2">综合分</th>
                      <th className="text-center py-2 px-2">信号</th>
                      <th className="text-left py-2 px-2">投票分布</th>
                      <th className="text-center py-2 px-2">共识度</th>
                      <th className="text-right py-2 px-2">现价</th>
                      <th className="text-right py-2 px-2">PE</th>
                      <th className="text-right py-2 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c, i) => {
                      const f = funds[c.ticker]
                      const isOpen = expanded === c.ticker
                      const sig = candidateSignal(c)
                      return (
                        <React.Fragment key={c.ticker}>
                          <tr className="border-b border-border/50 hover:bg-muted/30">
                            <td className="py-2.5 px-2 text-muted-foreground">{i + 1}</td>
                            <td className="py-2.5 px-2 font-mono font-semibold">{c.ticker}</td>
                            <td className="text-right py-2.5 px-2 font-mono">{candidateScore(c).toFixed(1)}</td>
                            <td className="text-center py-2.5 px-2">
                              <Badge variant={signalBadge(sig)}>{sig.toUpperCase()}</Badge>
                            </td>
                            <td className="py-2.5 px-2"><VotesBar votes={c.votes} /></td>
                            <td className="text-center py-2.5 px-2">
                              <Badge variant={consensusBadge(c.consensus ?? "")}
                                     className="text-[10px]">
                                {consensusLabel(c.consensus ?? "")}
                              </Badge>
                            </td>
                            <td className="text-right py-2.5 px-2 font-mono text-xs">
                              {f === undefined
                                ? <Skeleton className="h-3 w-12 ml-auto" />
                                : fmtPrice(fundNum(f, "regularMarketPrice")
                                            ?? fundNum(f, "currentPrice"))}
                            </td>
                            <td className="text-right py-2.5 px-2 font-mono text-xs">
                              {f === undefined
                                ? <Skeleton className="h-3 w-8 ml-auto" />
                                : fmtNum(fundNum(f, "trailingPE"))}
                            </td>
                            <td className="text-right py-2.5 px-2">
                              <Button variant="ghost" size="sm"
                                      onClick={() => setExpanded(isOpen ? null : c.ticker)}>
                                {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                              </Button>
                            </td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <td colSpan={9} className="bg-[var(--color-bg-secondary)] p-4">
                                <CandidateExpanded c={c} f={f} />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards — slimmer info per row, expand to full
                  CandidateExpanded for parity with desktop. */}
              <div className="md:hidden space-y-2">
                {candidates.map((c, i) => {
                  const sig = candidateSignal(c)
                  const isOpen = expanded === c.ticker
                  return (
                    <div key={c.ticker} className="border rounded-lg p-3">
                      <div className="flex justify-between items-center cursor-pointer"
                           onClick={() => setExpanded(isOpen ? null : c.ticker)}>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">#{i + 1}</span>
                          <span className="font-mono font-semibold">{c.ticker}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm">{candidateScore(c).toFixed(1)}</span>
                          <Badge variant={signalBadge(sig)}>{sig.toUpperCase()}</Badge>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <VotesBar votes={c.votes} />
                        <Badge variant={consensusBadge(c.consensus ?? "")}
                               className="text-[10px] ml-auto">
                          {consensusLabel(c.consensus ?? "")}
                        </Badge>
                      </div>
                      {isOpen && (
                        <div className="mt-3 pt-3 border-t border-border/40">
                          <CandidateExpanded c={c} f={funds[c.ticker]} />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/** v1.2: visual breakdown of bullish / neutral / bearish guru votes. */
function VotesBar({ votes }: { votes?: Votes }) {
  if (!votes || !votes.total) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  const { bullish, bearish, neutral, total } = votes
  return (
    <div className="flex items-center gap-2">
      <div className="flex w-20 h-2 rounded overflow-hidden bg-zinc-800">
        <div className="bg-emerald-500" style={{ width: `${bullish / total * 100}%` }} />
        <div className="bg-zinc-500/60" style={{ width: `${neutral / total * 100}%` }} />
        <div className="bg-red-500" style={{ width: `${bearish / total * 100}%` }} />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground whitespace-nowrap">
        <span className="text-emerald-400">{bullish}✓</span>{" "}
        <span>{neutral}=</span>{" "}
        <span className="text-red-400">{bearish}✗</span>
      </span>
    </div>
  )
}

/** v1.4: in-row expansion. Each guru card renders a structured summary
 *  (conclusion / supports / risk + theme_fit chip) instead of a flat
 *  240-char reasoning slice — that approach made every guru read the
 *  same off-theme paragraph because the v1.3 system prompt forced the
 *  theme statement into the reasoning lead. The full reasoning is
 *  still available via "展开完整推理".
 *
 *  Tooltip is now ``title={s.reasoning}`` (the full body) — the prior
 *  ``title={s.philosophy}`` was a copy/paste bug from the static
 *  guru-meta strip; philosophy is one stable sentence per guru and
 *  doesn't change per ticker, so it added no info on hover. */
function CandidateExpanded({ c, f }: {
  c: Candidate; f: Record<string, unknown> | null | undefined
}) {
  const sigs = candidateGuruScoresList(c)
  return (
    <div className="space-y-4">
      <div className="text-sm font-semibold">{c.ticker} — 大师评分详情</div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {sigs.map(s => (
          // key={s.guru} (not the array index) so React doesn't reuse
          // the wrong card's <details> open state when the parent sort
          // re-orders ``guru_signals`` (e.g. user toggles a sort header).
          <GuruSummaryCard key={s.guru} s={s} />
        ))}
      </div>

      {f && (
        <div className="rounded border border-border/50 bg-card/30 px-4 py-2">
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-x-4 gap-y-1 text-xs font-mono">
            <KV k="现价"     v={fmtPrice(fundNum(f, "regularMarketPrice")
                                          ?? fundNum(f, "currentPrice"))} />
            <KV k="200-SMA"  v={fmtPrice(fundNum(f, "twoHundredDayAverage"))} />
            <KV k="PE"       v={fmtNum(fundNum(f, "trailingPE"))} />
            <KV k="ROE"      v={fmtPct(fundNum(f, "returnOnEquity"))} />
            <KV k="D/E"      v={fmtNum(fundNum(f, "debtToEquity"), 0)} />
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline"
                onClick={() => { window.location.href = `/analysis?ticker=${c.ticker}` }}>
          <Zap className="h-3.5 w-3.5 mr-1" /> 跑 AI 分析
        </Button>
        <Button size="sm" variant="outline"
                onClick={() => {
                  fetch("/api/portfolio/track", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ ticker: c.ticker }),
                  }).catch(() => { /* surface failure via UI later */ })
                }}>
          加入观察列表
        </Button>
      </div>
    </div>
  )
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{k}</span>
      <span>{v}</span>
    </div>
  )
}

/* ── v1.4 guru summary card ──────────────────────────────────── */

/** Split ``reasoning`` on Chinese full-stop / period / newline. Empty
 *  segments dropped; we trim whitespace on each. Conservative — the
 *  backend ``_build_reasoning_format_instruction`` asks the LLM to use
 *  these as separators, but we tolerate paragraphs without them. */
function reasoningSentences(reasoning: string | null | undefined): string[] {
  if (!reasoning) return []
  return reasoning
    .split(/(?<=[。！？!?])\s*|\n+/)
    .map(s => s.trim())
    .filter(Boolean)
}

const RISK_KEYWORDS = [
  "风险", "担忧", "警惕", "需注意", "下行", "缺乏", "不足",
  "弱点", "局限", "limitation", "risk", "concern", "weak",
] as const

const SUPPORT_KEYWORDS = [
  "依据", "护城河", "PEG", "估值", "增长", "现金流", "护盘",
  "moat", "growth", "cash flow", "valuation",
] as const

/** Pick the sentence in ``sentences`` most likely to describe a risk.
 *  Falls back to the last sentence (which the v1.4 prompt asks the LLM
 *  to put the risk paragraph at), then to ``null`` so the card hides
 *  the risk line gracefully on legacy payloads. */
function pickRiskSentence(sentences: string[]): string | null {
  if (sentences.length === 0) return null
  for (const s of sentences) {
    if (RISK_KEYWORDS.some(k => s.toLowerCase().includes(k.toLowerCase()))) {
      return s
    }
  }
  // v1.4 prompt structure: third paragraph is the risk one. Fall back
  // to the trailing sentence(s) when no keyword match.
  return sentences.length >= 3 ? sentences[sentences.length - 1] : null
}

/** Pick 1-2 supporting sentences (the "core evidence" middle
 *  paragraph). Excludes whatever was picked as the risk sentence so
 *  the card doesn't repeat itself. */
function pickSupportSentences(sentences: string[], risk: string | null): string[] {
  if (sentences.length === 0) return []
  const conclusion = sentences[0]
  const supports = sentences
    .slice(1)
    .filter(s => s !== risk && s !== conclusion)
  // Prefer sentences that mention support keywords; fall back to
  // first-2 if no keyword hit.
  const ranked = supports.filter(s =>
    SUPPORT_KEYWORDS.some(k => s.toLowerCase().includes(k.toLowerCase())),
  )
  const pick = (ranked.length > 0 ? ranked : supports).slice(0, 2)
  return pick
}

/** Coerce a ``GuruSubAnalysis.score`` (sometimes string-encoded) to a
 *  finite number, or ``null`` if it can't. */
function subScore(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v
  if (typeof v === "string") {
    const n = Number(v.trim())
    if (Number.isFinite(n)) return n
  }
  return null
}

/** Render one guru's summary as a structured 3-line card. */
function GuruSummaryCard({ s }: { s: { guru: string } & GuruScore }) {
  const sentences = reasoningSentences(s.reasoning)
  const conclusion = sentences[0] ?? "—"
  const risk = pickRiskSentence(sentences)
  const supports = pickSupportSentences(sentences, risk)

  // Pull theme_fit out of sub_analyses for the chip; falls back to
  // null when the worker hasn't sent sub_analyses yet (legacy run).
  const themeFit = (s.sub_analyses ?? []).find(
    sa => (sa?.name ?? "").toLowerCase() === "theme_fit",
  )
  const themeFitScore = themeFit ? subScore(themeFit.score) : null

  return (
    <Card className="bg-card/50">
      <CardContent className="pt-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm">{s.guru}</span>
            {s.tier && (
              <Badge variant="muted" className="text-[9px]">{tierLabel(s.tier)}</Badge>
            )}
          </div>
          <Badge variant={signalBadge(s.signal)} className="text-[10px]">
            {(s.signal ?? "—").toUpperCase()}
          </Badge>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <div className="flex-1 h-1.5 bg-zinc-800 rounded overflow-hidden">
            <div className="h-full bg-primary"
                 style={{ width: `${(s.confidence ?? 0) * 100}%` }} />
          </div>
          <span className="font-mono text-muted-foreground text-[10px]">
            {((s.confidence ?? 0) * 100).toFixed(0)}%
          </span>
        </div>

        {/* theme_fit chip — small, informational. ``null`` score
            means the worker didn't ship sub_analyses (legacy row);
            we hide the chip rather than showing a fake "—". */}
        {themeFitScore !== null && (
          <div>
            <Badge
              variant={themeFitScore >= 6 ? "buy" : themeFitScore >= 3 ? "hold" : "sell"}
              className="text-[9px]"
              title={themeFit?.details ?? ""}
            >
              主题匹配 {themeFitScore.toFixed(1)}/10
            </Badge>
          </div>
        )}

        {/* 3-line structured summary. ``title`` is the full reasoning
            so an operator can hover for context without expanding —
            replaces the previous (broken) ``title={s.philosophy}``. */}
        <div className="space-y-1.5 text-xs leading-relaxed"
             title={s.reasoning ?? ""}>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
              结论
            </div>
            <div className="line-clamp-2">{conclusion}</div>
          </div>
          {supports.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                核心依据
              </div>
              <ul className="list-disc pl-4 space-y-0.5">
                {supports.map((sup, i) => (
                  <li key={i} className="line-clamp-2">{sup}</li>
                ))}
              </ul>
            </div>
          )}
          {risk && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                风险 / 反方
              </div>
              <div className="line-clamp-2 text-amber-300/80">{risk}</div>
            </div>
          )}
        </div>

        {/* Full reasoning expandable. ``<details>`` ships zero JS and
            the browser already remembers per-card open-state because
            the parent uses key={s.guru} (not the array index). */}
        {s.reasoning && s.reasoning.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">
              展开完整推理
            </summary>
            <div className="mt-1 max-h-60 overflow-y-auto whitespace-pre-line text-muted-foreground">
              {s.reasoning}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  )
}

/** Flatten guru scores into an array preserving the per-guru fields the
 *  expanded card needs (signal/confidence/reasoning/tier/philosophy). */
function candidateGuruScoresList(c: Candidate): Array<{ guru: string } & GuruScore> {
  if (Array.isArray(c.guru_signals) && c.guru_signals.length > 0) return c.guru_signals
  const map = candidateGuruScores(c)
  return Object.entries(map).map(([guru, s]) => ({ guru, ...s }))
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

/* ── Screening history (records + recent 3) ────────────────── */

interface ScreenSummary {
  candidates_count: number
  avg_score?: number
  votes?: { bullish: number; bearish: number; neutral: number }
  consensus_rate_pct?: number
  top3_tickers?: string[]
  roundtable_enabled?: boolean
  llm_calls?: number
  cache_hit_pct?: number
  duration_sec?: number
}

interface HistoryRow {
  task_id: string
  title: string
  status: string
  created_at: string
  completed_at: string | null
  duration_sec: number | null
  params: {
    nl_query: string
    market: string
    candidate_n: number
    gurus: string[]
    mode: string
    with_roundtable: boolean
  }
  summary: ScreenSummary | null
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return ""
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ""
  const dt = Date.now() - t
  if (dt < 60_000) return "刚刚"
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)} 分钟前`
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)} 小时前`
  return new Date(iso).toLocaleDateString("zh-CN")
}

/** Top-of-home 3 most recent successful runs. Hidden when empty so a
 *  brand-new user lands on a clean form, not an empty header. */
function RecentScreensCard() {
  const [items, setItems] = useState<HistoryRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiGet<{ items: HistoryRow[] }>("/api/screen/v3/history?limit=3")
      .then(r => setItems(r.items || []))
      .catch(() => {/* silent — not worth blocking the form */})
      .finally(() => setLoading(false))
  }, [])

  if (!loading && items.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">最近选股</CardTitle>
        <a
          href="/screener-v3/history"
          className="text-xs text-[var(--color-accent-blue)] hover:underline"
        >
          查看全部 →
        </a>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="grid gap-3 md:grid-cols-3">
            <Skeleton className="h-32" />
            <Skeleton className="h-32" />
            <Skeleton className="h-32" />
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {items.slice(0, 3).map(it => (
              <RecentScreenCard key={it.task_id} row={it} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RecentScreenCard({ row }: { row: HistoryRow }) {
  const s = row.summary
  return (
    <div
      onClick={() => {
        window.location.href = `/screener-v3?result=${row.task_id}`
      }}
      className="cursor-pointer rounded border bg-card/50 hover:border-primary/40 transition-colors p-3 space-y-1.5 text-xs"
    >
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">{fmtRelative(row.created_at)}</span>
        <Badge variant="muted" className="text-[9px]">
          {MODE_LABEL[row.params.mode] ?? row.params.mode}
        </Badge>
      </div>
      <div className="font-medium text-sm truncate" title={row.params.nl_query}>
        {row.params.nl_query || `${MARKET_LABEL[row.params.market]} 默认`}
      </div>
      <div className="text-muted-foreground">
        {MARKET_LABEL[row.params.market]} · 候选 {s?.candidates_count ?? "?"} ·{" "}
        {row.params.gurus.length} 大师
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono">
          均分 {s?.avg_score != null ? s.avg_score.toFixed(1) : "—"}
        </span>
        {s?.votes && (
          <span className="text-[10px]">
            <span className="text-emerald-400">{s.votes.bullish}✓</span>{" "}
            <span className="text-red-400">{s.votes.bearish}✗</span>
          </span>
        )}
      </div>
      <div className="font-mono text-[10px] text-muted-foreground truncate">
        Top: {(s?.top3_tickers ?? []).filter(Boolean).join(" · ") || "—"}
      </div>
    </div>
  )
}

/** Full paginated history page, mounted at /screener-v3/history. */
function ScreenerHistoryList() {
  const PAGE = 50
  const [items, setItems] = useState<HistoryRow[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modes, setModes] = useState<Set<string>>(new Set())
  const [markets, setMarkets] = useState<Set<string>>(new Set())
  const [includeFailed, setIncludeFailed] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const fetchPage = (reset: boolean) => {
    const off = reset ? 0 : offset
    const q = new URLSearchParams({
      limit: String(PAGE),
      offset: String(off),
      include_failed: includeFailed ? "true" : "false",
    })
    modes.forEach(m => q.append("mode", m))
    markets.forEach(m => q.append("market", m))
    setLoading(true)
    setError(null)
    apiGet<{ items: HistoryRow[]; total: number }>(`/api/screen/v3/history?${q}`)
      .then(r => {
        setTotal(r.total)
        setItems(reset ? r.items : [...items, ...r.items])
        setOffset(reset ? PAGE : offset + PAGE)
      })
      .catch(e => setError(e?.message ?? "加载失败"))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchPage(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    [...modes].sort().join(","),
    [...markets].sort().join(","),
    includeFailed,
  ])

  const toggleSet = (s: Set<string>, v: string,
                      setter: (s: Set<string>) => void) => {
    const next = new Set(s)
    if (next.has(v)) next.delete(v)
    else next.add(v)
    setter(next)
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost" size="sm"
          onClick={() => { window.location.href = "/screener-v3" }}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">选股记录</h1>
        <Badge variant="muted" className="ml-auto">{total} 条</Badge>
      </div>

      <Card>
        <CardContent className="py-3 flex flex-wrap items-center gap-3 text-xs">
          <span className="text-muted-foreground">模式:</span>
          {(["classic", "agent", "agent_rt"] as const).map(m => (
            <Chip
              key={m}
              active={modes.has(m)}
              onClick={() => toggleSet(modes, m, setModes)}
            >
              {MODE_LABEL[m]}
            </Chip>
          ))}
          <span className="text-muted-foreground ml-2">市场:</span>
          {(["us", "cn", "hk"] as const).map(m => (
            <Chip
              key={m}
              active={markets.has(m)}
              onClick={() => toggleSet(markets, m, setMarkets)}
            >
              {MARKET_LABEL[m]}
            </Chip>
          ))}
          <label className="flex items-center gap-1 ml-2 cursor-pointer">
            <Checkbox
              checked={includeFailed}
              onCheckedChange={v => setIncludeFailed(Boolean(v))}
            />
            包含失败
          </label>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      <Card>
        <CardContent className="pt-2">
          {loading && items.length === 0 && (
            <div className="space-y-2 py-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          )}
          {!loading && items.length === 0 && (
            <p className="text-sm text-muted-foreground py-8 text-center">
              暂无记录
            </p>
          )}
          {items.map(row => (
            <ScreenHistoryRow
              key={row.task_id}
              row={row}
              expanded={expanded === row.task_id}
              onToggle={() => setExpanded(
                expanded === row.task_id ? null : row.task_id,
              )}
            />
          ))}
          {offset < total && (
            <div className="text-center pt-3">
              <Button
                variant="ghost" size="sm"
                onClick={() => fetchPage(false)}
                disabled={loading}
              >
                加载更多 ({offset}/{total})
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ScreenHistoryRow({
  row, expanded, onToggle,
}: {
  row: HistoryRow
  expanded: boolean
  onToggle: () => void
}) {
  const s = row.summary
  const isFailed = row.status === "failed" || row.status === "cancelled"
  return (
    <div className="border-b py-2.5">
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={onToggle}>
          {expanded
            ? <ChevronDown className="h-4 w-4" />
            : <ChevronRight className="h-4 w-4" />}
        </Button>
        <span className="text-xs text-muted-foreground">
          {fmtRelative(row.created_at)}
        </span>
        <Badge variant="muted" className="text-[10px]">
          {MARKET_LABEL[row.params.market]}
        </Badge>
        <Badge variant="muted" className="text-[10px]">
          {MODE_LABEL[row.params.mode]}
        </Badge>
        {isFailed && (
          <Badge variant="default" className="text-[10px] bg-red-500/20 text-red-300">
            {row.status}
          </Badge>
        )}
        <span className="text-xs">候选 <b>{s?.candidates_count ?? "?"}</b></span>
        <span className="text-xs">
          均分{" "}
          <span className="font-mono">
            {s?.avg_score != null ? s.avg_score.toFixed(1) : "—"}
          </span>
        </span>
        {s?.votes && (
          <span className="text-xs">
            <span className="text-emerald-400">{s.votes.bullish}✓</span>{" "}
            <span className="text-red-400">{s.votes.bearish}✗</span>
          </span>
        )}
        <div className="flex gap-1 w-full sm:w-auto sm:ml-auto">
          <Button
            size="sm" variant="outline"
            className="flex-1 sm:flex-initial"
            onClick={() => {
              window.location.href = `/screener-v3?result=${row.task_id}`
            }}
          >
            查看
          </Button>
          <Button
            size="sm" variant="ghost"
            className="flex-1 sm:flex-initial"
            onClick={() => {
              window.location.href = `/screener-v3?prefill=${row.task_id}`
            }}
          >
            复制配置重跑
          </Button>
        </div>
      </div>
      {expanded && (
        <div className="pl-10 pr-2 mt-2 space-y-1.5 text-xs text-muted-foreground">
          {row.params.nl_query && (
            <div>
              NL 查询: "<span className="text-foreground">{row.params.nl_query}</span>"
            </div>
          )}
          <div>
            Top: {(s?.top3_tickers ?? []).filter(Boolean).join(" · ") || "—"}
          </div>
          <div>
            共识率 {s?.consensus_rate_pct ?? 0}% · 圆桌{" "}
            {s?.roundtable_enabled ? "✓" : "✗"} · {s?.llm_calls ?? 0} LLM call ·
            命中缓存 {s?.cache_hit_pct ?? 0}% · 耗时{" "}
            {s?.duration_sec
              ? `${Math.floor(s.duration_sec / 60)}m ${s.duration_sec % 60}s`
              : "—"}
          </div>
          <div>大师: {row.params.gurus.join(", ") || "—"}</div>
        </div>
      )}
    </div>
  )
}

/* ── Running view (?task=<id>) ─────────────────────────────── */

function ScreenerRunningView({ taskId }: { taskId: string }) {
  const [meta, setMeta] = useState<{ title?: string; status?: string } | null>(null)
  // ``mode`` controls whether ScreenerV3Progress renders the round-table
  // stage as a real node or a muted "未启用圆桌" placeholder. Read from
  // the catch-up GET ``params_json`` so deep-linking into a running task
  // (or refreshing) still shows the correct shape.
  const [mode, setMode] = useState<"classic" | "agent" | "agent_rt" | undefined>(undefined)
  const [terminalState, setTerminalState] = useState<
    "running" | "success" | "failed" | "cancelled" | null
  >(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  useEffect(() => {
    // Catch-up: if the task already finished while the user was away
    // (e.g. they opened the URL in a new tab hours later) we redirect
    // straight to the result page. The socket subscription below also
    // handles the live "task_completed" case.
    apiGet<{ status?: string; title?: string; params_json?: string }>(`/api/tasks/${taskId}`)
      .then(t => {
        setMeta({ status: t?.status, title: t?.title })
        if (t?.params_json) {
          try {
            const p = JSON.parse(t.params_json) as {
              mode?: string; with_roundtable?: boolean
            }
            const m = (p.with_roundtable ? "agent_rt" : p.mode) as
              "classic" | "agent" | "agent_rt" | undefined
            if (m === "classic" || m === "agent" || m === "agent_rt") {
              setMode(m)
            } else {
              setMode("agent")
            }
          } catch { setMode("agent") }
        }
        if (t?.status === "success") {
          window.location.replace(`/screener-v3?result=${taskId}`)
        } else if (t?.status === "cancelled") {
          // Surface the cancelled state distinctly — user gets to see
          // partial results banner instead of a generic "失败".
          setTerminalState("cancelled")
        } else if (t?.status === "failed") {
          setTerminalState("failed")
        } else {
          setTerminalState("running")
        }
      })
      .catch(() => setTerminalState("running"))

    let destroy: (() => void) | null = null
    let cancelled = false
    import("@/lib/socket").then(({ subscribeTaskStream }) => {
      if (cancelled) return
      const sub = subscribeTaskStream({
        taskIds: [taskId],
        onEvent: (env) => {
          if (env.event === "task_completed") {
            setTerminalState("success")
            // Tiny delay so the user sees the green tick on the DAG.
            setTimeout(
              () => window.location.replace(`/screener-v3?result=${taskId}`),
              600,
            )
          } else if (env.event === "task_failed") {
            setTerminalState("failed")
          } else if (env.event === "task_cancelled") {
            // Worker raised _CancelledError after persisting partial
            // results. Switch to the cancelled banner so the user can
            // jump to the partial result page instead of being stuck
            // on the running view forever.
            setTerminalState("cancelled")
          }
        },
        onStatusChange: () => { /* noop */ },
      })
      destroy = () => sub.destroy()
    }).catch(err => {
      // Don't lose the running view because the socket chunk failed —
      // log and let the catch-up GET above keep working.
      // eslint-disable-next-line no-console
      console.warn("subscribeTaskStream load failed:", err)
    })
    return () => {
      cancelled = true
      destroy?.()
    }
  }, [taskId])

  const stopRun = async () => {
    if (cancelling || terminalState !== "running") return
    if (!confirm("确认停止当前选股？已完成的大师评分仍可查看，未开始的部分将不再消耗 token。")) {
      return
    }
    setCancelling(true)
    setCancelError(null)
    try {
      const r = await fetch(`/api/tasks/${taskId}/cancel`, {
        method: "POST", credentials: "same-origin",
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        setCancelError(body.error || `取消失败 (${r.status})`)
      }
      // Status flip to "cancelled" arrives via the task_cancelled
      // socket event; the polling fallback in ScreenerV3Progress also
      // covers it. We don't optimistically setTerminalState here so a
      // 409 from a race (already finished) doesn't strand the UI.
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : "取消失败")
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost" size="sm"
          onClick={() => { window.location.href = "/screener-v3" }}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold">选股运行中</h1>
        {meta?.title && <Badge variant="muted">{meta.title}</Badge>}
        {terminalState === "running" && (
          <Button
            variant="outline" size="sm"
            onClick={stopRun}
            disabled={cancelling}
            className="ml-auto"
          >
            {cancelling ? "停止中…" : "停止"}
          </Button>
        )}
      </div>
      {cancelError && (
        <Alert variant="destructive">
          <AlertTitle>{cancelError}</AlertTitle>
        </Alert>
      )}
      <ScreenerV3Progress taskId={taskId} mode={mode} />
      <GuruParallelProgress taskId={taskId} />
      {terminalState === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>运行失败</AlertTitle>
          <AlertDescription>
            <Button
              variant="outline" size="sm"
              onClick={() => {
                window.location.href = `/screener-v3?prefill=${taskId}`
              }}
            >
              复制配置重跑
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {terminalState === "cancelled" && (
        <Alert variant="default">
          <AlertTitle>已停止</AlertTitle>
          <AlertDescription>
            已完成的大师评分已保存为部分结果。
            <div className="mt-2 flex gap-2">
              <Button
                variant="outline" size="sm"
                onClick={() => {
                  window.location.href = `/screener-v3?result=${taskId}`
                }}
              >
                查看部分结果
              </Button>
              <Button
                variant="ghost" size="sm"
                onClick={() => {
                  window.location.href = `/screener-v3?prefill=${taskId}`
                }}
              >
                复制配置重跑
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
      {terminalState === "running" && (
        <p className="text-xs text-center text-muted-foreground">
          完成后自动跳转 · 也可在{" "}
          <a href="/tasks" className="underline">任务中心</a>{" "}
          跨类型查看
        </p>
      )}
    </div>
  )
}

/** Per-(guru, ticker) live cell matrix. Subscribes to the same socket
 *  channel ScreenerRunningView uses but listens for different events
 *  emitted by the v3 worker. Hidden until the first event arrives so
 *  classic-mode (no LLM) doesn't render an empty placeholder. */
type UnitStatus = "running" | "done" | "cached" | "failed"

function GuruParallelProgress({ taskId }: { taskId: string }) {
  const [units, setUnits] = useState<Record<string, UnitStatus>>({})

  useEffect(() => {
    let destroy: (() => void) | null = null
    let cancelled = false
    import("@/lib/socket").then(({ subscribeTaskStream }) => {
      if (cancelled) return
      const sub = subscribeTaskStream({
        taskIds: [taskId],
        onEvent: (env) => {
          if (env.event !== "guru_unit_done"
              && env.event !== "guru_unit_start"
              && env.event !== "guru_unit_failed") return
          const p = (env.payload || {}) as {
            guru?: string; ticker?: string; cached?: boolean
          }
          const key = `${p.guru || "?"}::${p.ticker || "?"}`
          let status: UnitStatus
          if (env.event === "guru_unit_failed") status = "failed"
          else if (env.event === "guru_unit_start") status = "running"
          else status = p.cached ? "cached" : "done"
          // Once a unit has flipped to a terminal state (done/cached/failed)
          // a stale guru_unit_start arriving late MUST NOT down-grade it
          // back to "running" — guard against the race.
          setUnits(prev => {
            const existing = prev[key]
            if (existing && existing !== "running" && status === "running") {
              return prev
            }
            return { ...prev, [key]: status }
          })
        },
        onStatusChange: () => { /* noop */ },
      })
      destroy = () => sub.destroy()
    }).catch(err => {
      // eslint-disable-next-line no-console
      console.warn("guru parallel subscribe failed:", err)
    })
    return () => {
      cancelled = true
      destroy?.()
    }
  }, [taskId])

  const entries = Object.entries(units)
  if (entries.length === 0) return null
  const settled = entries.filter(
    ([, s]) => s === "done" || s === "cached" || s === "failed",
  ).length
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          大师并发进度 ({settled} / {entries.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 font-mono text-[10px]">
          {entries.map(([key, status]) => {
            const [guru, ticker] = key.split("::")
            return (
              <div
                key={key}
                className={cn(
                  "rounded border px-2 py-1 truncate",
                  status === "done"
                    && "border-emerald-500/40 text-emerald-400",
                  status === "cached"
                    && "border-sky-500/40 text-sky-400",
                  status === "failed"
                    && "border-red-500/40 text-red-400",
                  status === "running"
                    && "border-zinc-500/30 text-zinc-300 animate-pulse",
                )}
                title={status}
              >
                {guru} · {ticker}{status === "cached" ? " ⚡" : ""}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
