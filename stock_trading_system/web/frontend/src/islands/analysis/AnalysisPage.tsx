import { useEffect, useState, useRef, useCallback, lazy, Suspense } from "react"
import {
  Sparkles, Send, ArrowLeft, Clock, Newspaper, BarChart3, Scale,
  ExternalLink, ChevronDown, ChevronRight,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PipelineDAG } from "@/components/shared/PipelineDAG"
import { ErrorBoundary } from "@/components/shared/ErrorBoundary"
import type { TVChartState } from "@/components/shared/TVChart"
import { apiGet, apiPost, apiDel } from "@/lib/api"
// react-markdown + remark-gfm + rehype-sanitize together are ~70kB
// gzipped — we only need them on the analysis-detail tabs body, never
// on the form page or the running view. Lazy-load via React.lazy so
// they end up in their own chunk and only fetch when a user actually
// renders the body.
const MarkdownBody = lazy(() => import("@/components/shared/MarkdownBody"))
// TVChart pulls lightweight-charts (~80kB gz). Same story — defer.
const TVChart = lazy(() =>
  import("@/components/shared/TVChart").then(m => ({ default: m.TVChart })),
)
// 8 structured tab cards — each barrel module pulls its own helpers
// (stat formatters, badge variants). Splitting the whole barrel into
// one chunk keeps the entry small while preserving render simplicity.
const AnalysisCards = lazy(() => import("@/components/analysis/lazy-bundle"))
import type { RenderingDict } from "@/components/analysis"

/** Minimal shape descriptor — inlined here (not imported from
 *  ``shared/defensive``) so this entry chunk does NOT pull
 *  ``defensive.ts`` into itself. If it did, Rollup would put
 *  ``defensive.ts`` in the analysis entry chunk and the lazy-bundle
 *  chunk (which also needs ``defensive.ts``) would import back into
 *  the entry — a chunk-level circular dependency that broke production
 *  /analysis/17 (lazy-bundle's destructured imports resolved before
 *  the entry's re-export was initialised, so the cards saw ``undefined``
 *  helpers and threw).
 *
 *  This helper is for telemetry only — keys + types, never values, so
 *  we don't leak report bodies into the browser console / Sentry. */
function describeShapeForTelemetry(v: unknown): unknown {
  if (v === null) return "null"
  if (Array.isArray(v)) return `array(${v.length})`
  if (typeof v === "object") {
    const out: Record<string, string> = {}
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      out[k] = val === null
        ? "null"
        : Array.isArray(val) ? `array(${val.length})` : typeof val
    }
    return out
  }
  return typeof v
}

interface AnalysisDetail {
  id: string; ticker: string; signal: string; date: string
  summary?: string
  // analysis-rendering v1.7+ — ``confidence`` is the LLM-derived
  // ``rendering.summary.confidence`` mapped to 0.85/0.5/0.25; ``confidence_level``
  // exposes the original "high"/"medium"/"low" so the UI can show a
  // 中文 label, and ``confidence_source`` is "llm_structured_output"
  // (or null for rows without rendering_json). The UI MUST NOT fall
  // back to ``advice.confidence`` — that's the per-user execution
  // confidence (StrategyEngine heuristic), not the analysis confidence.
  confidence?: number | null
  confidence_level?: "high" | "medium" | "low" | null
  confidence_source?: string | null
  risk_level?: string; created_at?: string
  market_report?: string; sentiment_report?: string; news_report?: string
  fundamentals_report?: string; investment_debate?: string
  risk_assessment?: string; trade_decision?: string
  analysts?: Record<string, string>
  advice_json?: string
  task_id?: string
  // v1.14
  created_by_name?: string | null
  provider?: string | null
  model?: string | null
  duration_sec?: number | null
  bookmarked?: boolean
  advice?: Record<string, unknown> | null
  // v1.16: depth UX hint persisted on the shared row
  depth?: "quick" | "standard" | "deep" | null
  // v1.19: per-tab structured cards. The DTO emits a parsed dict — clients
  // never see ``rendering_json`` raw. Missing or null values fall back to
  // the markdown body (kept inside a ``<details>`` collapsible).
  rendering?: RenderingDict | null
  // v1.20: canonical trade action parsed from ``trade_decision`` text.
  // Always prefer ``decision_action`` over ``signal`` when present —
  // ``signal_mismatch=true`` means the stored signal disagreed with the
  // trader's explicit ``FINAL TRANSACTION PROPOSAL: **X**`` (legacy row;
  // we surface a small "已校正" hint so the user knows we corrected it).
  decision_action?: "Buy" | "Sell" | "Hold" | null
  signal_mismatch?: boolean
  // v1.6 — paper-trade v1.3 F3 LLM-extracted "execution summary" column
  // on ``analysis_history``. Server already exposes this via the detail
  // DTO (app.py:1564); we forward it into <OverviewCard> so the summary
  // tab's Decision banner gets a structured "执行总结" block instead of
  // surfacing the text only as a tab-level small footnote. Schema layer
  // (rendering.summary Pydantic) is intentionally NOT touched.
  executive_summary?: string | null
}

/** Resolve the canonical action to display. Prefers
 *  ``detail.decision_action`` (v1.20+ canon — parsed from the trader's
 *  ``FINAL TRANSACTION PROPOSAL: **X**``) over ``detail.signal``
 *  (historical column — sometimes drifted from the trader's text). */
function canonicalSignal(detail: Pick<AnalysisDetail, "decision_action" | "signal">): string {
  return detail.decision_action || detail.signal || ""
}

interface RecentAnalysisRow {
  id: number; ticker: string; signal: string; date: string
  created_at?: string; created_by_name?: string | null
}

/** v1.22 unified inbox row. ``/api/history?include_running=true`` returns
 *  a discriminated list mixing in-flight tasks with completed analyses. */
type InboxRow =
  | {
      kind: "task"
      task_id: string
      ticker: string
      depth: "quick" | "standard" | "deep" | null
      status: "pending" | "running" | "failed" | "cancelled" | string
      submitted_at: string | null
      progress_pct: number
      progress_step?: string | null
      error: string | null
      created_by_name: string | null
    }
  | {
      kind: "analysis"
      id: number
      ticker: string
      signal: string
      date: string
      created_at: string
      created_by_name: string | null
      provider: string | null
      model: string | null
      duration_sec: number | null
      task_id: string | null
      depth: "quick" | "standard" | "deep" | null
      bookmarked: boolean
      // analysis-rendering v1.7 — LLM-derived confidence on the inbox
      // row. ``null`` for rows without rendering_json (legacy / extraction
      // failed). The ``confidence`` numeric is unused on the row chip
      // for now (the level chip is enough on a list); detail page uses
      // it in the gauge. Keep the field so future tooltips can read it.
      confidence?: number | null
      confidence_level?: "high" | "medium" | "low" | null
      confidence_source?: string | null
    }

function inboxSortKey(row: InboxRow): string {
  return row.kind === "task"
    ? (row.submitted_at ?? "")
    : (row.created_at ?? "")
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return ""
  const t = Date.parse(iso.replace(" ", "T") + "Z")
  if (Number.isNaN(t)) return ""
  const dt = Date.now() - t
  if (dt < 60_000) return "刚刚"
  if (dt < 3_600_000) return `${Math.floor(dt / 60_000)} 分钟前`
  if (dt < 86_400_000) return `${Math.floor(dt / 3_600_000)} 小时前`
  return new Date(t).toLocaleDateString("zh-CN")
}

const TASK_STATUS_LABEL: Record<string, string> = {
  pending: "排队中", running: "运行中",
  failed: "失败",   cancelled: "已取消",
}

type AnalysisDepth = "quick" | "standard" | "deep"

function depthLabel(d: AnalysisDepth | string | null | undefined): string {
  switch ((d || "").toLowerCase()) {
    case "quick":    return "快速"
    case "deep":     return "深度"
    case "standard": return "标准"
    default:         return "标准"
  }
}

/** Translate the LLM-derived confidence level (rendering.summary.confidence
 * or rendering.Decision.conviction) to a Chinese chip label. Used both
 * on the detail header and on inbox rows so users see the same words. */
function confidenceLevelLabel(
  level: "high" | "medium" | "low" | string | null | undefined,
): string {
  switch ((level || "").toLowerCase()) {
    case "high":   return "高置信"
    case "medium": return "中置信"
    case "low":    return "低置信"
    default:       return ""
  }
}

interface OHLCVRow {
  date: string; open: number; high: number; low: number; close: number; volume: number
}

/** Real-news item from /api/news/<ticker>. yfinance shape — fields are
 * optional because alternate providers (Polygon, akshare) populate
 * different subsets. */
interface NewsItem {
  title: string
  source?: string
  published?: string
  url?: string
}

/** Read a numeric fundamentals field into a typed value, returning ``null``
 * for anything we can't safely cast — guards against akshare returning
 * "—" / "N/A" strings for missing metrics. */
function fundNum(fund: Record<string, unknown> | null,
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

const fmtNum = (v: number, d: number) => v.toFixed(d)
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`

interface TaskSubmitResult { task_id: string; status: string }

function signalVariant(signal: string): "buy" | "sell" | "hold" | "default" {
  const s = signal?.toLowerCase() ?? ""
  if (s.includes("buy") || s.includes("bullish")) return "buy"
  if (s.includes("sell") || s.includes("bearish")) return "sell"
  if (s.includes("hold") || s.includes("neutral")) return "hold"
  return "default"
}

function getIdFromUrl(): string | null {
  const match = window.location.pathname.match(/\/analysis\/([^/]+)/)
  return match?.[1] ?? null
}

/** Heuristic: does this text look like a Python dict repr or raw JSON
 *  blob that escaped the v1.20 normalizer (legacy rows or pre-fix data)?
 *  Triggers a short banner on the raw-output panel so the user knows the
 *  structured cards above are the canonical view. */
function looksLikeRawDict(content: string): boolean {
  const t = content.trim()
  if (!t) return false
  if (t.length > 8000) return false  // skip Markdown-with-fenced-JSON noise
  // Python dict repr signature: starts with `{'…':` (single-quote keys)
  // or `{"…":` and never sees a Markdown heading or paragraph.
  const startsLikeRepr = /^\{['"][\w_]+['"]\s*:/.test(t)
  if (!startsLikeRepr) return false
  const hasMarkdown = /(^|\n)#{1,6}\s|\n\n[一-鿿]/.test(t)
  return !hasMarkdown
}

/** UUID = task ID (running state); pure digits or "analysis_history:N" = completed history ID */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function isTaskId(id: string): boolean {
  return UUID_RE.test(id)
}

const REPORT_TABS = [
  { key: "summary", label: "概览" },
  { key: "Market", label: "市场/技术面" },
  { key: "Sentiment", label: "情绪面" },
  { key: "News", label: "新闻" },
  { key: "Fundamentals", label: "基本面" },
  { key: "Investment Debate", label: "多空辩论" },
  { key: "Risk Assessment", label: "风险评估" },
  { key: "Decision", label: "决策" },
] as const

const DEPTH_OPTIONS: { value: AnalysisDepth; label: string; hint: string }[] = [
  { value: "quick",    label: "快速", hint: "~30s · ~$0.05 · 跳过辩论/反思" },
  { value: "standard", label: "标准", hint: "~2min · ~$0.20 · 7 Agent 默认" },
  { value: "deep",     label: "深度", hint: "~5min · ~$0.80 · 启用迭代" },
]

/** v1.22: legacy ``/analysis/<task_uuid>`` URLs are folded into the
 *  unified inbox. We replaceState to ``/analysis?task=<uuid>`` so the
 *  bookmark resolves correctly + the inbox auto-scrolls to the matching
 *  row. Done at module init so the first paint already has the clean
 *  URL. Returns the anchor uuid (or null) for the inbox to scroll to. */
function consumeLegacyTaskUuid(urlId: string | null): string | null {
  if (!urlId || !isTaskId(urlId)) {
    return new URLSearchParams(window.location.search).get("task")
  }
  try {
    window.history.replaceState(null, "", `/analysis?task=${urlId}`)
  } catch (e) {
    // history API blocked (rare — tests / sandboxed iframes). The URL
    // stays as-is; inbox still renders. Surface so we notice in dev.
    // eslint-disable-next-line no-console
    console.warn("inbox: replaceState for legacy /analysis/<uuid> failed", e)
  }
  return urlId
}

export function AnalysisPage() {
  const [urlId] = useState<string | null>(getIdFromUrl)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // v1.22: legacy task-uuid path is now a query-string anchor, not its
  // own running-view route. Capture once at mount so further inbox
  // refreshes don't re-trigger the scroll.
  const [taskAnchor] = useState<string | null>(() => consumeLegacyTaskUuid(urlId))
  // Detail-route taskId still tracked for the (now-unreachable from URL)
  // running view fallback path. Keeps the existing AnalysisRunningView
  // component callable for any code path that pre-set it.
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskTicker, setTaskTicker] = useState<string>("")

  // Form state
  const [ticker, setTicker] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [depth, setDepth] = useState<AnalysisDepth>("standard")
  const [submitting, setSubmitting] = useState(false)
  // v1.22 unified inbox: in-flight tasks + completed analyses in one
  // list. Replaces the old "最近分析" 5-card strip + the standalone
  // /history page.
  const [inbox, setInbox] = useState<InboxRow[]>([])
  const [runningTotal, setRunningTotal] = useState(0)
  // analysis-progress-truth-source v1.0: live progress overlay for
  // running task rows, keyed by task_id. Populated from task_progress
  // / analysis_pipeline events on the unified envelope stream and
  // merged into RunningRow's percent + step text so the row stays in
  // sync with the pipeline DAG without round-tripping /api/history.
  // Cleared on terminal events (handled by the inbox subscription).
  const [liveProgress, setLiveProgress] = useState<
    Record<string, { pct: number; step: string | null; stage: string | null }>
  >({})
  // Client-side ticker filter — instant feedback while typing. Backend
  // supports ``ticker`` query param too (used for prefiltering when
  // arriving with a deep-link like ``/analysis?ticker=AAPL``).
  const [inboxTickerQ, setInboxTickerQ] = useState(
    () => new URLSearchParams(window.location.search).get("ticker") ?? "",
  )

  // Completed analysis ID (numeric) — strip "analysis_history:" prefix if present
  const detailId = urlId && !isTaskId(urlId)
    ? (urlId.startsWith("analysis_history:") ? urlId.slice("analysis_history:".length) : urlId)
    : null

  // Load completed analysis
  useEffect(() => {
    if (!detailId) return
    setLoading(true); setError(null)
    apiGet<AnalysisDetail>(`/api/history/${detailId}`)
      .then(setDetail)
      .catch(err => setError(err.message ?? "Failed to load"))
      .finally(() => setLoading(false))
  }, [detailId])

  // Running task: fetch task info for ticker name
  useEffect(() => {
    if (!taskId) return
    apiGet<{ type: string; params_json?: string; title?: string }>(`/api/tasks/${taskId}`)
      .then(t => {
        try {
          const p = t.params_json ? JSON.parse(t.params_json) : {}
          setTaskTicker(p.ticker || "")
        } catch { /* ignore */ }
      })
      .catch(() => {})
  }, [taskId])

  const handleSubmit = async () => {
    if (!ticker.trim()) return
    setSubmitting(true); setError(null)
    const submittedTicker = ticker.toUpperCase()
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis",
        params: { ticker: submittedTicker, date, depth },
      })
      if (res.task_id) {
        // v1.22: stay on the inbox; prepend an optimistic running row
        // so the user sees feedback immediately. The websocket
        // subscription wired below refreshes the row to a completed
        // analysis card once the task settles.
        const optimistic: InboxRow = {
          kind: "task",
          task_id: res.task_id,
          ticker: submittedTicker,
          depth,
          status: "pending",
          submitted_at: new Date().toISOString().slice(0, 19).replace("T", " "),
          progress_pct: 0,
          progress_step: null,
          error: null,
          created_by_name: null,
        }
        setInbox(prev => [optimistic, ...prev])
        setRunningTotal(n => n + 1)
        setTicker("")
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally { setSubmitting(false) }
  }

  // v1.22: unified inbox fetch. Pulls running tasks (this user only,
  // server-side scoped) merged with the latest completed analyses.
  // Only fires on the form view — detail / running views don't need it.
  const refreshInbox = useCallback(() => {
    apiGet<{
      items: InboxRow[]
      running_total?: number
      completed_total?: number
    }>("/api/history?include_running=true&limit=20")
      .then(r => {
        const items = Array.isArray(r.items) ? r.items : []
        items.sort((a, b) => inboxSortKey(b).localeCompare(inboxSortKey(a)))
        setInbox(items)
        setRunningTotal(r.running_total ?? 0)
      })
      .catch(() => setInbox([]))
  }, [])

  useEffect(() => {
    if (detailId || taskId) return
    refreshInbox()
  }, [detailId, taskId, refreshInbox])

  // v1.22 task anchor: arriving via legacy ``/analysis/<task_uuid>`` URL
  // (now folded into ``?task=<uuid>``) — once the inbox lands, scroll
  // the matching row into view so the user lands on it directly. Runs
  // once after the first refresh populates ``inbox``.
  useEffect(() => {
    if (!taskAnchor || inbox.length === 0) return
    const t = window.setTimeout(() => {
      const el = document.querySelector(`[data-task-id="${taskAnchor}"]`)
      el?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, 250)
    return () => window.clearTimeout(t)
  }, [taskAnchor, inbox.length])

  // analysis-progress-truth-source v1.0: subscribe to the unified task
  // envelope stream and merge progress into a local map keyed by task_id.
  // We render `liveProgress[task_id] ?? row.progress_pct` so the inbox
  // row percent / step text track the analyzer pipeline in real time
  // without waiting for refreshInbox(). On terminal events we still
  // refreshInbox() to flip 运行中 → CompletedRow.
  //
  // The seven-stage pipeline is mapped to 5%→85% by the analysis worker
  // (advice=90%, finalize=98%, success=100%); analysis_pipeline events
  // are kept as a redundant fallback so a single dropped task_progress
  // does not freeze the row.
  useEffect(() => {
    if (detailId || taskId) return
    const taskIds = inbox
      .filter((it): it is Extract<InboxRow, { kind: "task" }> =>
        it.kind === "task" && (it.status === "pending" || it.status === "running"),
      )
      .map(it => it.task_id)
    if (taskIds.length === 0) return
    let cancelled = false
    let sub: { destroy: () => void } | null = null
    import("@/lib/socket").then(({ subscribeTaskStream }) => {
      if (cancelled) return
      sub = subscribeTaskStream({
        taskIds,
        onEvent: (env) => {
          const tid = env.task_id
          if (!tid) return
          const p = (env.payload || {}) as Record<string, unknown>
          if (env.event === "task_progress") {
            const pct = typeof p.progress === "number" ? p.progress : null
            const step = typeof p.step === "string" ? p.step : null
            const stage = typeof p.stage === "string" ? p.stage : null
            if (pct == null) return
            setLiveProgress(prev => ({
              ...prev,
              [tid]: {
                pct: Math.max(prev[tid]?.pct ?? 0, pct),
                step: step ?? prev[tid]?.step ?? null,
                stage: stage ?? prev[tid]?.stage ?? null,
              },
            }))
          } else if (env.event === "analysis_pipeline") {
            // Fallback: if task_progress was dropped we still nudge the
            // pct off the floor when we see step_done / pipeline_done.
            const ptype = typeof p.type === "string" ? p.type : ""
            if (ptype === "step_done") {
              const idx = typeof p.index === "number" ? p.index : 0
              const total = typeof p.total === "number" && p.total > 0 ? p.total : 7
              const pct = 5 + Math.round(((idx + 1) / total) * 80)
              const step = typeof p.label === "string" ? p.label : null
              const stage = typeof p.step === "string" ? p.step : null
              setLiveProgress(prev => ({
                ...prev,
                [tid]: {
                  pct: Math.max(prev[tid]?.pct ?? 0, pct),
                  step: step ?? prev[tid]?.step ?? null,
                  stage: stage ?? prev[tid]?.stage ?? null,
                },
              }))
            } else if (ptype === "pipeline_done") {
              setLiveProgress(prev => ({
                ...prev,
                [tid]: {
                  pct: Math.max(prev[tid]?.pct ?? 0, 85),
                  step: "整理结果中",
                  stage: "pipeline_done",
                },
              }))
            }
          } else if (
            env.event === "task_completed"
            || env.event === "task_failed"
            || env.event === "task_cancelled"
          ) {
            // Drop the live entry — the next /api/history pull will
            // replace the row with a CompletedRow / failure row.
            setLiveProgress(prev => {
              if (!(tid in prev)) return prev
              const next = { ...prev }
              delete next[tid]
              return next
            })
            refreshInbox()
          }
        },
        onStatusChange: () => {},
      })
    }).catch(e => {
      // Socket transport unavailable — surface the failure but don't
      // block the page; the manual refresh button still works.
      // eslint-disable-next-line no-console
      console.warn("inbox: socket subscribe failed", e)
    })
    return () => { cancelled = true; sub?.destroy() }
  }, [inbox, detailId, taskId, refreshInbox])

  // ── Running state: show PipelineDAG ─────────────────────────
  if (taskId) {
    return <AnalysisRunningView
      taskId={taskId}
      ticker={taskTicker}
      onComplete={(analysisId) => {
        // Smoothly transition to detail view
        window.history.replaceState(null, "", `/analysis/${analysisId}`)
        setTaskId(null)
        setLoading(true)
        apiGet<AnalysisDetail>(`/api/history/${analysisId}`)
          .then(setDetail)
          .catch(err => setError(err.message ?? "Failed to load"))
          .finally(() => setLoading(false))
      }}
    />
  }

  // ── Completed detail ────────────────────────────────────────
  if (detailId && loading) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Skeleton className="h-8 w-48" /><Skeleton className="h-6 w-32" /><Skeleton className="h-64" />
    </div>
  )

  if (detailId && error) return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <Alert variant="destructive"><AlertTitle>加载失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>
      <Button variant="outline" onClick={() => window.location.href = "/analysis"}>
        <ArrowLeft className="h-4 w-4 mr-1" />返回
      </Button>
    </div>
  )

  if (detailId && detail) return <AnalysisDetailView detail={detail} />

  // ── Submit form ─────────────────────────────────────────────
  // analysis-inbox v1.1: 发起分析卡在前，分析记录卡在后。提交后乐观插
  // 入的运行中行立刻出现在下方记录区，符合"先输入再看历史"的产品意图。
  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Sparkles className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">AI 分析</h1>
      </div>

      <Card>
        <CardHeader><CardTitle>发起分析</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 form-row-mobile sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <label className="text-sm text-muted-foreground">股票代码</label>
              <Input placeholder="如 AAPL, TSLA" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} />
            </div>
            <div className="w-full sm:w-44 space-y-1.5">
              <label className="text-sm text-muted-foreground">分析日期</label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
            <Button onClick={handleSubmit} disabled={submitting || !ticker.trim()}>
              {submitting ? <><Clock className="h-4 w-4 mr-1 animate-spin" />提交中...</> : <><Send className="h-4 w-4 mr-1" />开始分析</>}
            </Button>
          </div>

          <div className="space-y-2">
            <div className="text-sm text-muted-foreground">分析深度</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {DEPTH_OPTIONS.map(opt => (
                <label
                  key={opt.value}
                  className={
                    "flex items-start gap-2 rounded-lg border p-3 cursor-pointer text-sm " +
                    (depth === opt.value
                      ? "border-primary/60 bg-primary/5"
                      : "border-border")
                  }
                >
                  <input
                    type="radio"
                    name="analysis-depth"
                    value={opt.value}
                    checked={depth === opt.value}
                    onChange={() => setDepth(opt.value)}
                    className="mt-0.5"
                  />
                  <div>
                    <div className="font-semibold">{opt.label}</div>
                    <div className="text-xs text-muted-foreground">{opt.hint}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {error && <Alert variant="destructive" className="mt-2"><AlertTitle>提交失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        </CardContent>
      </Card>

      {/* v1.22 unified inbox (rendered below the form per analysis-inbox
          v1.1): running tasks + completed analyses in one list. Replaces
          the standalone /history page; /history now 301-redirects here.
          Inline ``PipelineDAG`` for running rows gives users live
          progress without leaving the page. */}
      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-sm">分析记录</CardTitle>
          <div className="flex items-center gap-2">
            {runningTotal > 0 && (
              <Badge variant="default" className="text-[10px]">
                <Clock className="h-3 w-3 mr-1 animate-spin" />
                {runningTotal} 运行中
              </Badge>
            )}
            <Button variant="ghost" size="sm" onClick={refreshInbox}>
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <InboxToolbar
            ticker={inboxTickerQ}
            onTicker={setInboxTickerQ}
            total={inbox.length}
          />
          {inbox.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              暂无分析记录，提交一个新分析后会在这里显示进度
            </p>
          ) : (() => {
              const filterUpper = inboxTickerQ.trim().toUpperCase()
              const visible = filterUpper
                ? inbox.filter(it => it.ticker.includes(filterUpper))
                : inbox
              if (visible.length === 0) {
                return (
                  <p className="text-sm text-muted-foreground py-6 text-center">
                    无匹配记录
                  </p>
                )
              }
              return visible.map(it => it.kind === "task" ? (
                <RunningRow
                  key={it.task_id}
                  row={it}
                  live={liveProgress[it.task_id]}
                  highlight={taskAnchor === it.task_id}
                  onSettled={refreshInbox}
                />
              ) : (
                <CompletedRow
                  key={it.id}
                  row={it}
                  onChanged={refreshInbox}
                />
              ))
            })()}
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Running view: PipelineDAG + skeleton tabs ─────────────── */

function AnalysisRunningView({ taskId, ticker, onComplete }: {
  taskId: string; ticker: string
  onComplete: (analysisId: string) => void
}) {
  const [completed, setCompleted] = useState(false)

  useEffect(() => {
    // Socket.IO is only needed in the *running* view (we tail
    // task_completed and bounce to the detail page on terminal events).
    // History detail pages never need it, so dynamic-import keeps the
    // socket chunk out of the entry bundle on those reads.
    let cancelled = false
    let destroy: (() => void) | null = null
    import("@/lib/socket").then(({ subscribeTaskStream }) => {
      if (cancelled) return
      const sub = subscribeTaskStream({
        taskIds: [taskId],
        onEvent: (env) => {
          if (env.event === "task_completed") {
            setCompleted(true)
            // Extract analysis_id from result_ref
            const ref = (env.payload as { result_ref?: string })?.result_ref ?? ""
            const m = ref.match?.(/(\d+)/)
            if (m) {
              setTimeout(() => onComplete(m[1]), 1000)
            }
          }
        },
        onStatusChange: () => {},
      })
      destroy = () => sub.destroy()
    })
    return () => {
      cancelled = true
      destroy?.()
    }
  }, [taskId, onComplete])

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => window.location.href = "/analysis"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold font-mono">{ticker || "分析中..."}</h1>
        <Badge variant="default">运行中</Badge>
      </div>

      <PipelineDAG taskId={taskId} />

      {/* Skeleton placeholders for the tabs */}
      {!completed && (
        <Card>
          <CardContent className="pt-6 space-y-4">
            <div className="flex gap-2 border-b pb-2">
              {REPORT_TABS.map(t => <Skeleton key={t.key} className="h-6 w-16" />)}
            </div>
            <Skeleton className="h-40" />
          </CardContent>
        </Card>
      )}

      {completed && (
        <Alert variant="success">
          <AlertTitle>分析完成</AlertTitle>
          <AlertDescription>正在加载结果...</AlertDescription>
        </Alert>
      )}

      <div className="text-center">
        <a href={`/tasks/${taskId}`} className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
          <ExternalLink className="h-3 w-3" /> 查看任务详情
        </a>
      </div>
    </div>
  )
}

/* ── Detail view with TVChart K-line + pipeline + quick-info + 7-tab ── */

function AnalysisDetailView({ detail }: { detail: AnalysisDetail }) {
  const [klineData, setKlineData] = useState<OHLCVRow[]>([])
  const [klineState, setKlineState] = useState<TVChartState>("loading")
  const [activeTab, setActiveTab] = useState("summary")
  const tabsRef = useRef<HTMLDivElement>(null)
  // Viewport-gated K-line: don't fetch /api/quote/history or load
  // lightweight-charts until the chart card scrolls into view. Most
  // users land on /analysis/<id>, glance at the summary card, then
  // bounce — that previously cost 90 days of OHLCV + 80kB of chart
  // code on every visit.
  const klineSectionRef = useRef<HTMLDivElement>(null)
  const [klineVisible, setKlineVisible] = useState(false)

  // Primary: /api/quote/history (days-based, dedicated for chart rendering).
  // Fallback: /api/chart/{ticker} (period-based, predates the days API).
  // We track state explicitly so the chart container — which always mounts
  // — can show loading / empty / error overlays without unmounting itself.
  const refetchKline = useCallback(async () => {
    if (!detail.ticker) {
      setKlineState("empty")
      return
    }
    setKlineState("loading")
    try {
      const primary = await apiGet<{ bars?: OHLCVRow[] }>(
        `/api/quote/history?ticker=${detail.ticker}&days=90`,
      )
      const bars = primary.bars ?? []
      if (bars.length > 0) {
        setKlineData(bars)
        setKlineState("ok")
        return
      }
      // Empty primary → try the legacy chart endpoint.
      const fallback = await apiGet<{ data?: OHLCVRow[] }>(
        `/api/chart/${detail.ticker}?period=3mo&interval=1d`,
      )
      const fbBars = fallback.data ?? []
      if (fbBars.length > 0) {
        setKlineData(fbBars)
        setKlineState("ok")
      } else {
        setKlineState("empty")
      }
    } catch (err: unknown) {
      // Primary failed → try the fallback before declaring error.
      try {
        const fallback = await apiGet<{ data?: OHLCVRow[] }>(
          `/api/chart/${detail.ticker}?period=3mo&interval=1d`,
        )
        const fbBars = fallback.data ?? []
        if (fbBars.length > 0) {
          setKlineData(fbBars)
          setKlineState("ok")
          return
        }
        setKlineState("empty")
      } catch {
        setKlineState("error")
      }
    }
  }, [detail.ticker])

  // Watch the K-line section. Once visible we both flag the chart for
  // mounting and trigger the OHLCV fetch. Re-runs are guarded by
  // klineVisible so the observer fires exactly once per page load.
  useEffect(() => {
    if (klineVisible) {
      refetchKline()
      return
    }
    const node = klineSectionRef.current
    if (!node || typeof IntersectionObserver === "undefined") {
      // No IO support → fall back to immediate fetch (Safari < 12.1, JSDOM).
      setKlineVisible(true)
      return
    }
    const io = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting)) {
        setKlineVisible(true)
        io.disconnect()
      }
    }, { rootMargin: "200px" })
    io.observe(node)
    return () => io.disconnect()
  }, [klineVisible, refetchKline])

  // Build report content map (8 tabs)
  const reportContent: Record<string, string> = {}
  if (detail.summary) reportContent["summary"] = detail.summary
  if (detail.analysts) {
    for (const [key, val] of Object.entries(detail.analysts)) {
      reportContent[key] = typeof val === "string" ? val : JSON.stringify(val, null, 2)
    }
  }
  // The "决策" tab is sourced from analysis_history.trade_decision rather
  // than analysts.* — the worker stores it as a top-level column.
  if (detail.trade_decision) reportContent["Decision"] = detail.trade_decision

  // Parse advice_json so the catch suppresses bad rows. We only need the
  // side effect of validating it parses; the rendered UI reads structured
  // fields directly, not this blob.
  try {
    if (detail.advice_json && typeof detail.advice_json === "string") {
      JSON.parse(detail.advice_json)
    }
  } catch { /* ignore malformed advice payloads */ }

  // v1.19.1: quick-info cards now hit the same data APIs the analyzer
  // uses (yfinance/Polygon) instead of heuristic-parsing the LLM markdown.
  // News is fetched per-detail-mount; Fundamentals same. Debate reuses
  // the structured rendering already on the detail.
  const [news, setNews] = useState<NewsItem[]>([])
  const [fund, setFund] = useState<Record<string, unknown> | null>(null)
  useEffect(() => {
    if (!detail.id) return
    // v1.16: one aggregated request instead of two parallel XHRs.
    // Backend handles upstream failures and returns partial results,
    // so we don't need to retry on individual sub-fetches here.
    interface QuickInfoResp {
      news?: NewsItem[]
      fundamentals?: Record<string, unknown> | null
    }
    apiGet<QuickInfoResp>(`/api/analysis/${detail.id}/quick-info`)
      .then(r => {
        setNews((r?.news ?? []).slice(0, 3))
        setFund(r?.fundamentals ?? null)
      })
      .catch(() => {
        setNews([])
        setFund(null)
      })
  }, [detail.id])

  const scrollToTab = (tabKey: string) => {
    setActiveTab(tabKey)
    tabsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  // Detect if analysis is still running (created < 5 min ago, no summary)
  const isRecent = detail.created_at && (Date.now() - new Date(detail.created_at).getTime()) < 5 * 60 * 1000
  const isRunning = isRecent && !detail.summary && !!detail.task_id

  // Action-button state
  const [bookmarked, setBookmarked] = useState<boolean>(Boolean(detail.bookmarked))
  const [bookmarkBusy, setBookmarkBusy] = useState(false)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [paperBusy, setPaperBusy] = useState(false)

  const handleReanalyze = async () => {
    setActionMsg(null)
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis",
        params: { ticker: detail.ticker, date: detail.date, depth: "standard" },
      })
      if (res.task_id) window.location.href = `/analysis/${res.task_id}`
    } catch (err: unknown) {
      setActionMsg(err instanceof Error ? `再分析失败：${err.message}` : "再分析失败")
    }
  }

  const handleTrack = async () => {
    setActionMsg(null)
    try {
      await apiPost("/api/portfolio/track", {
        ticker: detail.ticker, analysis_id: detail.id,
      })
      setActionMsg("✓ 已加入观察列表（不会自动下单）")
      setTimeout(() => setActionMsg(null), 2500)
    } catch (err: unknown) {
      setActionMsg(err instanceof Error ? `追踪失败：${err.message}` : "追踪失败")
    }
  }

  interface PaperTrackResult {
    ok: boolean
    session_id?: number
    plan_id?: number
    num_orders?: number
    triggered?: number
    error?: string
  }

  const handlePaperTrack = async () => {
    if (paperBusy) return
    setPaperBusy(true)
    setActionMsg(null)
    try {
      const res = await apiPost<PaperTrackResult>("/api/paper/track", {
        analysis_id: detail.id,
      })
      if (!res.ok) {
        setActionMsg(`提交失败：${res.error ?? "process_analysis failed"}`)
        return
      }
      const triggered = res.triggered ?? 0
      const numOrders = res.num_orders ?? 0
      if (triggered > 0) {
        setActionMsg(`✓ 纸面交易计划已生成，立即成交 ${triggered} 单`)
      } else if (numOrders > 0) {
        setActionMsg(`✓ 纸面交易计划已生成，${numOrders} 单待触发`)
      } else {
        setActionMsg("✓ 已生成空计划（建议中无可执行订单）")
      }
      setTimeout(() => setActionMsg(null), 3500)
    } catch (err: unknown) {
      setActionMsg(err instanceof Error ? `提交失败：${err.message}` : "提交失败")
    } finally {
      setPaperBusy(false)
    }
  }

  const handleExport = (fmt: "md" | "pdf") => {
    // Browser download — no JSON parsing needed.
    window.location.href = `/api/history/${detail.id}/export?format=${fmt}`
  }

  const handleShare = async () => {
    const url = `${window.location.origin}/analysis/${detail.id}`
    try {
      await navigator.clipboard.writeText(url)
      setActionMsg("✓ 链接已复制")
      setTimeout(() => setActionMsg(null), 2500)
    } catch {
      // Fallback: surface the URL inline so the user can copy it manually.
      setActionMsg(`分享链接：${url}`)
    }
  }

  const handleBookmark = async () => {
    setBookmarkBusy(true)
    setActionMsg(null)
    const next = !bookmarked
    try {
      const r = await apiPost<{ ok: boolean; bookmarked: boolean }>(
        `/api/history/${detail.id}/bookmark`,
        { bookmarked: next },
      )
      setBookmarked(Boolean(r.bookmarked))
    } catch (err: unknown) {
      setActionMsg(err instanceof Error ? `收藏失败：${err.message}` : "收藏失败")
    } finally {
      setBookmarkBusy(false)
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/analysis"}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-xl font-bold font-mono">{detail.ticker}</h1>
          <Badge variant={signalVariant(canonicalSignal(detail))}>
            {canonicalSignal(detail) || "N/A"}
          </Badge>
          {detail.signal_mismatch && (
            <span
              className="text-[10px] text-amber-400"
              title={`原存储信号: ${detail.signal} · 决策正文: ${detail.decision_action}`}
            >
              信号已按最终决策校正
            </span>
          )}
          {detail.confidence != null ? (
            <span
              className="text-sm text-muted-foreground"
              title={
                detail.confidence_source === "llm_structured_output"
                  ? "AI 分析置信度（LLM 结构化输出）"
                  : "AI 分析置信度"
              }
            >
              置信度 {(detail.confidence * 100).toFixed(0)}%
              {detail.confidence_level && (
                <>
                  {" · "}
                  <span
                    className={
                      detail.confidence_level === "high"
                        ? "text-emerald-400"
                        : detail.confidence_level === "low"
                        ? "text-amber-400"
                        : "text-zinc-300"
                    }
                  >
                    {confidenceLevelLabel(detail.confidence_level)}
                  </span>
                </>
              )}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground/70" title="LLM 结构化摘要缺失">
              置信度暂无
            </span>
          )}
        </div>
        {/* Action buttons (right-aligned on desktop, wraps below on mobile) */}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={handleReanalyze}>再次分析</Button>
          <Button variant="outline" size="sm" onClick={handleTrack}>加入观察列表</Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handlePaperTrack}
            disabled={paperBusy}
          >
            {paperBusy ? "提交中…" : "按此建议纸面交易"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("md")}>导出 Markdown</Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("pdf")}>导出 PDF</Button>
          <Button variant="outline" size="sm" onClick={handleShare}>分享链接</Button>
          <Button
            variant={bookmarked ? "default" : "outline"}
            size="sm"
            onClick={handleBookmark}
            disabled={bookmarkBusy}
          >
            {bookmarked ? "★ 已收藏" : "☆ 收藏"}
          </Button>
        </div>
      </div>

      {/* Provenance / metadata row */}
      <div className="text-xs text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
        {detail.created_by_name && <span>创建者：{detail.created_by_name}</span>}
        {detail.provider && (
          <span>Provider：{detail.provider}{detail.model ? ` / ${detail.model}` : ""}</span>
        )}
        {detail.depth && (
          <span>深度：{depthLabel(detail.depth)}</span>
        )}
        {detail.duration_sec != null && (
          <span>耗时：{Number(detail.duration_sec).toFixed(1)}s</span>
        )}
        {detail.created_at && <span>创建于：{detail.created_at}</span>}
      </div>

      {actionMsg && (
        <div className="text-xs text-muted-foreground">{actionMsg}</div>
      )}

      {/* Pipeline DAG (shown for running tasks or as completed timeline) */}
      {isRunning && detail.task_id && (
        <PipelineDAG taskId={detail.task_id} onAllDone={() => window.location.reload()} />
      )}

      {/* analysis-rendering v1.4: AI 分析内容上移到第一屏。
          顺序: Header (untouched above) → PipelineDAG (running only,
          untouched above) → ★ 8-tab report → K-line → Quick-info.
          Stats 3-card row 删除（信息已通过 Header Badge / Provenance
          「创建于」/ OverviewCard.RatingBadge + ConfidenceMeter 全部
          表达，独立行只是冗余）。 */}

      {/* 8-tab report — AI 分析核心，第一屏可见 */}
      <Card ref={tabsRef} data-testid="analysis-tabs">
        <CardContent className="pt-6">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="tabs-scrollable w-full justify-start bg-transparent border-b rounded-none pb-0 gap-0">
              {REPORT_TABS.map(tab => (
                <TabsTrigger key={tab.key} value={tab.key}
                  className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-3 pb-2">
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {REPORT_TABS.map(tab => {
              const content = reportContent[tab.key] || ""
              // Pass raw struct straight through — the lazy-bundle
              // dispatcher does its own client-side normalize. Doing
              // it here would force ``defensive.ts`` into this entry
              // chunk and re-create the lazy/entry import cycle.
              const struct = detail.rendering?.[tab.key as keyof RenderingDict]
              const hasStruct = !!struct
              return (
                <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
                  {/* Per-tab boundary: a single malformed structured card
                      should NOT take down the whole detail page (the
                      production /analysis/17 white-screen). On error we
                      hide just this tab's structured card and let the
                      Markdown ``<details>`` below render the same
                      content from the analyst report text. */}
                  {hasStruct ? (
                    <ErrorBoundary
                      resetKey={`${detail.id}:${tab.key}`}
                      onError={(err) => {
                        // Telemetry only — never echo report bodies.
                        // The shape helper walks one level deep and
                        // emits field name + type so an operator can
                        // diagnose which key is malformed without us
                        // leaking PII or analyst conclusions to logs.
                        // eslint-disable-next-line no-console
                        console.error("[analysis card] render failed", {
                          analysis_id: detail.id,
                          tab_key: tab.key,
                          error_name: err.name,
                          error_message: err.message,
                          struct_shape: describeShapeForTelemetry(struct),
                        })
                      }}
                      fallback={({ error }) => (
                        <CardFallback error={error} />
                      )}
                    >
                      <Suspense fallback={<Skeleton className="h-32 w-full" />}>
                        <AnalysisCards
                          tabKey={tab.key}
                          data={struct}
                          executiveSummary={
                            tab.key === "summary"
                              ? (detail.executive_summary ?? null)
                              : undefined
                          }
                        />
                      </Suspense>
                    </ErrorBoundary>
                  ) : null}
                  {content ? (
                    <details className="rounded border border-border/50">
                      <summary className="cursor-pointer px-4 py-2 text-xs text-muted-foreground hover:bg-muted/30">
                        {hasStruct
                          ? "原始模型输出（点击展开 · 仅供调试参考）"
                          : "原始模型输出"}
                      </summary>
                      <div className="prose prose-invert prose-sm max-w-none px-4 py-3 max-h-[600px] overflow-y-auto text-[var(--color-text-secondary)]">
                        {looksLikeRawDict(content) && (
                          <div className="mb-3 rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300 not-prose">
                            原始输出格式异常（疑似 Python dict / JSON），已优先展示结构化摘要。
                          </div>
                        )}
                        <ErrorBoundary
                          resetKey={`${detail.id}:${tab.key}:md`}
                          fallback={
                            <pre className="text-xs whitespace-pre-wrap">{content}</pre>
                          }
                        >
                          <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                            <MarkdownBody>{content}</MarkdownBody>
                          </Suspense>
                        </ErrorBoundary>
                      </div>
                    </details>
                  ) : (!hasStruct && (
                    <p className="text-sm text-muted-foreground py-8 text-center">暂无数据</p>
                  ))}
                </TabsContent>
              )
            })}
          </Tabs>
        </CardContent>
      </Card>

      {/* K-line chart — viewport-gated. The container always mounts so
          IntersectionObserver has something to watch; TVChart itself is
          lazy-loaded only after the section scrolls into view, and the
          /api/quote/history fetch fires from the same observer. */}
      <Card ref={klineSectionRef} data-testid="kline-section">
        <CardHeader><CardTitle className="text-sm">K 线走势（近 3 个月）</CardTitle></CardHeader>
        <CardContent>
          {klineVisible ? (
            <Suspense fallback={<Skeleton className="w-full" style={{ height: 380 }} />}>
              <TVChart data={klineData} state={klineState} onRetry={refetchKline} height={380} />
            </Suspense>
          ) : (
            <Skeleton className="w-full" style={{ height: 380 }} />
          )}
        </CardContent>
      </Card>

      {/* Quick-info cards (news / fundamentals / debate) — v1.19.1 hits
          the same data APIs the analyzer uses so users see real headlines
          + real PE/ROE/D-E instead of regex extracts of LLM markdown.
          v1.4: moved below K-line as 次要参考 — onClick → scrollToTab
          仍向上滚动到 Tab 区域。 */}
      <div className="grid gap-4 md:grid-cols-3 grid-collapse-mobile" data-testid="quickinfo-row">
        <QuickInfoCard
          icon={<Newspaper className="h-4 w-4" />}
          title="最近新闻"
          onClick={() => scrollToTab("News")}
        >
          {news.length === 0 ? (
            <p className="text-xs text-muted-foreground">暂无新闻数据</p>
          ) : (
            <ul className="space-y-1.5">
              {news.map((n, i) => (
                <li key={i} className="text-xs leading-snug">
                  <span className="line-clamp-2">{n.title}</span>
                  {(n.source || n.published) && (
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      {n.source}{n.source && n.published ? " · " : ""}{n.published}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QuickInfoCard>

        <QuickInfoCard
          icon={<BarChart3 className="h-4 w-4" />}
          title="基本面指标"
          onClick={() => scrollToTab("Fundamentals")}
        >
          {!fund ? (
            <p className="text-xs text-muted-foreground">暂无基本面数据</p>
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">
              {(() => {
                const pe   = fundNum(fund, "trailingPE")
                const pb   = fundNum(fund, "priceToBook")
                const roe  = fundNum(fund, "returnOnEquity")
                const de   = fundNum(fund, "debtToEquity")
                const pm   = fundNum(fund, "profitMargins")
                const rg   = fundNum(fund, "revenueGrowth")
                const rows = [
                  pe   != null && <KV key="pe"  k="PE"     v={fmtNum(pe, 1)} />,
                  pb   != null && <KV key="pb"  k="P/B"    v={fmtNum(pb, 1)} />,
                  roe  != null && <KV key="roe" k="ROE"    v={fmtPct(roe)} />,
                  de   != null && <KV key="de"  k="D/E"    v={fmtNum(de, 0)} />,
                  pm   != null && <KV key="pm"  k="净利率"  v={fmtPct(pm)} />,
                  rg   != null && <KV key="rg"  k="营收增长" v={fmtPct(rg)} />,
                ].filter(Boolean)
                return rows.length > 0 ? rows : (
                  <p className="text-xs text-muted-foreground col-span-2">
                    指标暂不可用
                  </p>
                )
              })()}
            </div>
          )}
        </QuickInfoCard>

        <QuickInfoCard
          icon={<Scale className="h-4 w-4" />}
          title="多空辩论"
          onClick={() => scrollToTab("Investment Debate")}
        >
          {(() => {
            const debate = detail.rendering?.["Investment Debate"]
            const synthesis = detail.rendering?.summary?.debate_synthesis
            if (debate) {
              const bull = debate.bull_arguments?.length ?? 0
              const bear = debate.bear_arguments?.length ?? 0
              return (
                <div className="space-y-1.5">
                  <div className="text-xs">
                    看多 <b>{bull}</b> · 看空 <b>{bear}</b>
                    {debate.verdict && (
                      <>
                        {" "}·{" "}
                        <Badge variant="muted" className="text-[10px]">
                          {debate.verdict}
                        </Badge>
                      </>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-3">
                    {debate.key_disagreement || debate.neutral_synthesis}
                  </p>
                </div>
              )
            }
            if (synthesis) {
              return (
                <p className="text-xs text-muted-foreground line-clamp-3">
                  {synthesis.verdict}
                </p>
              )
            }
            return <p className="text-xs text-muted-foreground">暂无辩论数据</p>
          })()}
        </QuickInfoCard>
      </div>

      {/* K-line chart — viewport-gated. The container always mounts so
          IntersectionObserver has something to watch; TVChart itself is
          lazy-loaded only after the section scrolls into view, and the
          /api/quote/history fetch fires from the same observer. */}
      <Card ref={klineSectionRef}>
        <CardHeader><CardTitle className="text-sm">K 线走势（近 3 个月）</CardTitle></CardHeader>
        <CardContent>
          {klineVisible ? (
            <Suspense fallback={<Skeleton className="w-full" style={{ height: 380 }} />}>
              <TVChart data={klineData} state={klineState} onRetry={refetchKline} height={380} />
            </Suspense>
          ) : (
            <Skeleton className="w-full" style={{ height: 380 }} />
          )}
        </CardContent>
      </Card>

      {/* 7-tab report */}
      <Card ref={tabsRef}>
        <CardContent className="pt-6">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="tabs-scrollable w-full justify-start bg-transparent border-b rounded-none pb-0 gap-0">
              {REPORT_TABS.map(tab => (
                <TabsTrigger key={tab.key} value={tab.key}
                  className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-3 pb-2">
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {REPORT_TABS.map(tab => {
              const content = reportContent[tab.key] || ""
              // Pass raw struct straight through — the lazy-bundle
              // dispatcher does its own client-side normalize. Doing
              // it here would force ``defensive.ts`` into this entry
              // chunk and re-create the lazy/entry import cycle.
              const struct = detail.rendering?.[tab.key as keyof RenderingDict]
              const hasStruct = !!struct
              return (
                <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
                  {/* Per-tab boundary: a single malformed structured card
                      should NOT take down the whole detail page (the
                      production /analysis/17 white-screen). On error we
                      hide just this tab's structured card and let the
                      Markdown ``<details>`` below render the same
                      content from the analyst report text. */}
                  {hasStruct ? (
                    <ErrorBoundary
                      resetKey={`${detail.id}:${tab.key}`}
                      onError={(err) => {
                        // Telemetry only — never echo report bodies.
                        // The shape helper walks one level deep and
                        // emits field name + type so an operator can
                        // diagnose which key is malformed without us
                        // leaking PII or analyst conclusions to logs.
                        // eslint-disable-next-line no-console
                        console.error("[analysis card] render failed", {
                          analysis_id: detail.id,
                          tab_key: tab.key,
                          error_name: err.name,
                          error_message: err.message,
                          struct_shape: describeShapeForTelemetry(struct),
                        })
                      }}
                      fallback={({ error }) => (
                        <CardFallback error={error} />
                      )}
                    >
                      <Suspense fallback={<Skeleton className="h-32 w-full" />}>
                        <AnalysisCards
                          tabKey={tab.key}
                          data={struct}
                          executiveSummary={
                            tab.key === "summary"
                              ? (detail.executive_summary ?? null)
                              : undefined
                          }
                        />
                      </Suspense>
                    </ErrorBoundary>
                  ) : null}
                  {content ? (
                    <details className="rounded border border-border/50">
                      <summary className="cursor-pointer px-4 py-2 text-xs text-muted-foreground hover:bg-muted/30">
                        {hasStruct
                          ? "原始模型输出（点击展开 · 仅供调试参考）"
                          : "原始模型输出"}
                      </summary>
                      <div className="prose prose-invert prose-sm max-w-none px-4 py-3 max-h-[600px] overflow-y-auto text-[var(--color-text-secondary)]">
                        {looksLikeRawDict(content) && (
                          <div className="mb-3 rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300 not-prose">
                            原始输出格式异常（疑似 Python dict / JSON），已优先展示结构化摘要。
                          </div>
                        )}
                        <ErrorBoundary
                          resetKey={`${detail.id}:${tab.key}:md`}
                          fallback={
                            <pre className="text-xs whitespace-pre-wrap">{content}</pre>
                          }
                        >
                          <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                            <MarkdownBody>{content}</MarkdownBody>
                          </Suspense>
                        </ErrorBoundary>
                      </div>
                    </details>
                  ) : (!hasStruct && (
                    <p className="text-sm text-muted-foreground py-8 text-center">暂无数据</p>
                  ))}
                </TabsContent>
              )
            })}
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Fallback used when a structured card render throws ───── */

/** Per-tab fallback shown when ``AnalysisCards`` throws inside the
 *  ErrorBoundary. Distinguish failure modes so operators can act on
 *  them differently:
 *
 *    * Asset/preload failures (``Unable to preload`` / chunk-load
 *      errors) — static-resource bug, NOT a data issue. v1.5 was a
 *      Vite ``base`` mis-config that produced ``/assets/card-*.css``
 *      404s; the user-facing copy now names "组件加载失败" so a
 *      future asset-path regression is identified at a glance.
 *    * Render-time failures (TypeError on a malformed payload) —
 *      data-shape issue. Copy stays "结构化摘要暂不可用" because
 *      the markdown body below contains the same content.
 *
 *  We do NOT print the error stack or struct payload here — that
 *  goes to ``console.error`` where it's filterable.
 */
function CardFallback({ error }: { error: Error }) {
  const msg = error.message || ""
  const isAssetLoad =
    msg.includes("Unable to preload") ||
    msg.includes("Failed to fetch dynamically imported module") ||
    msg.includes("Loading chunk") ||
    msg.includes("Importing a module script failed")
  const headline = isAssetLoad
    ? "结构化摘要组件加载失败，已显示完整论述。"
    : "结构化摘要暂不可用，已显示完整论述。"
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
      <div>{headline}</div>
      <details className="mt-1">
        <summary className="cursor-pointer text-[10px] opacity-70">
          错误详情（开发者）
        </summary>
        <code className="block mt-1 text-[10px] font-mono whitespace-pre-wrap opacity-80">
          {error.name}: {error.message}
        </code>
      </details>
    </div>
  )
}

/* ── Quick-info card ─────────────────────────────────────── */

function QuickInfoCard({ icon, title, onClick, children }: {
  icon: React.ReactNode
  title: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <Card
      className="cursor-pointer hover:border-primary/30 transition-colors"
      onClick={onClick}
    >
      <CardContent className="pt-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[var(--color-accent-blue)]">{icon}</span>
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {title}
          </span>
        </div>
        {children}
        <span className="text-[10px] text-[var(--color-accent-blue)] mt-2 inline-block">
          查看详情 →
        </span>
      </CardContent>
    </Card>
  )
}

/** Two-column key/value row used by the Fundamentals quick-info grid. */
function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{k}</span>
      <span>{v}</span>
    </div>
  )
}

/* ── v1.22 inbox toolbar + rows ─────────────────────────────── */

/** Inbox toolbar — ticker filter + total count. Spec calls for richer
 *  scope/bookmark/provider/signal filters; this minimum surface keeps
 *  the path open without committing to backend additions that don't
 *  yet exist on /api/history (scope/bookmark filters need new query
 *  params + tests). */
function InboxToolbar({ ticker, onTicker, total }: {
  ticker: string
  onTicker: (v: string) => void
  total: number
}) {
  return (
    <div className="flex items-center gap-2 pb-2 border-b border-border/40">
      <div className="relative flex-1 max-w-xs">
        <Input
          value={ticker}
          onChange={e => onTicker(e.target.value.toUpperCase())}
          placeholder="按股票代码筛选"
          className="h-8 text-sm"
        />
      </div>
      <span className="text-xs text-muted-foreground ml-auto">
        共 {total} 条
      </span>
    </div>
  )
}

/** v1.22 RunningRow — embeds the live ``PipelineDAG`` so users can
 *  see step progress without leaving /analysis. Mobile collapses to
 *  a status bar by default; desktop expands. ``onSettled`` fires when
 *  PipelineDAG signals all-done so the parent can refresh the inbox
 *  and flip the row to a CompletedRow. */
function RunningRow({ row, highlight, onSettled }: {
  row: Extract<InboxRow, { kind: "task" }>
  highlight?: boolean
  onSettled: () => void
}) {
  const [collapsed, setCollapsed] = useState(() =>
    typeof window !== "undefined"
      && window.matchMedia?.("(max-width: 575.98px)").matches,
  )
  const isFailure = row.status === "failed" || row.status === "cancelled"
  const label = TASK_STATUS_LABEL[row.status] ?? row.status

  const cancel = async () => {
    if (!confirm(`确认取消 ${row.ticker} 的分析?`)) return
    try {
      await apiPost(`/api/tasks/${row.task_id}/cancel`, {})
      onSettled()
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("inbox: cancel failed", e)
    }
  }

  return (
    <div
      data-task-id={row.task_id}
      className={
        "rounded border bg-card/40 px-3 py-2 text-sm space-y-2 " +
        (highlight ? "border-primary/60 ring-1 ring-primary/30" : "border-border/50")
      }
    >
      <div className="flex items-center gap-3 flex-wrap">
        {isFailure
          ? <span className="h-2 w-2 rounded-full bg-destructive shrink-0" />
          : <Clock className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />}
        <span className="font-mono font-semibold">{row.ticker || "—"}</span>
        <Badge variant="muted" className="text-[10px]">
          {depthLabel(row.depth)}
        </Badge>
        <Badge
          variant={isFailure ? "sell" : "default"}
          className="text-[10px]"
        >
          {label}
        </Badge>
        {!isFailure && row.progress_pct > 0 && (
          <span className="text-xs text-muted-foreground font-mono">
            {row.progress_pct}%
          </span>
        )}
        <span className="text-xs text-muted-foreground ml-auto">
          {fmtRelative(row.submitted_at)}
        </span>
        {!isFailure && (
          <Button
            variant="ghost" size="sm"
            onClick={() => setCollapsed(c => !c)}
            title={collapsed ? "展开管线" : "折叠管线"}
            className="h-6 px-1.5"
          >
            {collapsed
              ? <ChevronRight className="h-3.5 w-3.5" />
              : <ChevronDown className="h-3.5 w-3.5" />}
          </Button>
        )}
        {!isFailure && (
          <Button
            variant="ghost" size="sm" onClick={cancel}
            title="取消" className="h-6 px-1.5"
          >
            取消
          </Button>
        )}
        <a
          href={`/tasks/${row.task_id}`}
          className="text-xs text-[var(--color-accent-blue)] hover:underline shrink-0"
        >
          详情
        </a>
      </div>
      {/* Inline pipeline DAG — visible on desktop / when expanded.
          Mobile collapsed view drops to a thin progress bar so the
          inbox stays scannable on a small screen. */}
      {!isFailure && !collapsed && (
        <div className="pl-1">
          <PipelineDAG taskId={row.task_id} onAllDone={onSettled} />
        </div>
      )}
      {!isFailure && collapsed && row.progress_pct > 0 && (
        <div className="h-1 bg-muted rounded overflow-hidden">
          <div
            className="h-full bg-primary transition-all"
            style={{ width: `${Math.min(100, row.progress_pct)}%` }}
          />
        </div>
      )}
      {isFailure && row.error && (
        <p className="text-xs text-destructive">{row.error}</p>
      )}
    </div>
  )
}

/** v1.22 CompletedRow — extracted from the v1.18 HistoryPage logic.
 *  Click-row to expand reveals trade-decision summary + provider/model
 *  metadata; bookmark toggle + delete (creator/admin) are inline. */
function CompletedRow({ row, onChanged }: {
  row: Extract<InboxRow, { kind: "analysis" }>
  onChanged: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [bookmarked, setBookmarked] = useState(row.bookmarked)
  const [busy, setBusy] = useState(false)

  // Lazy-fetch the row's detail when first expanded so the inbox
  // doesn't pay for /api/history/<id> N+1 requests up front.
  const toggle = async () => {
    const next = !expanded
    setExpanded(next)
    if (next && !detail) {
      try {
        const d = await apiGet<AnalysisDetail>(`/api/history/${row.id}`)
        setDetail(d)
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("inbox: detail fetch failed", e)
      }
    }
  }

  const toggleBookmark = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (busy) return
    setBusy(true)
    const next = !bookmarked
    setBookmarked(next)  // optimistic
    try {
      await apiPost(`/api/history/${row.id}/bookmark`, { bookmarked: next })
    } catch (err) {
      setBookmarked(!next)  // rollback
      // eslint-disable-next-line no-console
      console.warn("inbox: bookmark toggle failed", err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`删除 #${row.id} ${row.ticker} 的分析记录?`)) return
    try {
      await apiDel(`/api/history/${row.id}`)
      onChanged()
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("inbox: delete failed", err)
    }
  }

  return (
    <div
      className="rounded border border-border/50 bg-card/40 hover:border-primary/40 transition-colors"
    >
      <div
        onClick={toggle}
        className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer"
      >
        {expanded
          ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
        <span className="font-mono font-semibold">{row.ticker}</span>
        <Badge variant={signalVariant(row.signal || "")} className="text-[10px]">
          {row.signal || "—"}
        </Badge>
        <Badge variant="muted" className="text-[10px]">{depthLabel(row.depth)}</Badge>
        {/* analysis-rendering v1.7 — show LLM confidence chip when
            available; absent for legacy rows without rendering_json. */}
        {row.confidence_level && (
          <Badge
            variant="muted"
            className={
              "text-[10px] " +
              (row.confidence_level === "high"
                ? "text-emerald-400"
                : row.confidence_level === "low"
                ? "text-amber-400"
                : "text-zinc-300")
            }
            title="AI 分析置信度（LLM 结构化输出）"
          >
            {confidenceLevelLabel(row.confidence_level)}
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">{row.date}</span>
        {row.created_by_name && (
          <span className="text-xs text-muted-foreground hidden sm:inline">
            · {row.created_by_name}
          </span>
        )}
        <span className="text-xs text-muted-foreground ml-auto">
          {fmtRelative(row.created_at)}
        </span>
        <button
          type="button"
          onClick={toggleBookmark}
          disabled={busy}
          className={
            "text-xs shrink-0 px-1.5 py-0.5 rounded hover:bg-muted/40 " +
            (bookmarked ? "text-amber-400" : "text-muted-foreground")
          }
          title={bookmarked ? "取消收藏" : "收藏"}
        >
          {bookmarked ? "★" : "☆"}
        </button>
        <a
          href={`/analysis/${row.id}`}
          onClick={e => e.stopPropagation()}
          className="text-xs text-[var(--color-accent-blue)] hover:underline shrink-0"
        >
          打开
        </a>
        <button
          type="button"
          onClick={remove}
          className="text-xs text-destructive/80 hover:text-destructive shrink-0 px-1.5 py-0.5 rounded hover:bg-destructive/10"
          title="删除"
        >
          删除
        </button>
      </div>
      {expanded && (
        <div className="px-3 pb-3 pt-1 text-xs text-muted-foreground border-t border-border/30 space-y-1">
          {detail?.trade_decision ? (
            <p className="leading-relaxed line-clamp-6 whitespace-pre-line">
              {detail.trade_decision.slice(0, 600)}
              {detail.trade_decision.length > 600 && "…"}
            </p>
          ) : (
            <p className="italic">加载摘要…</p>
          )}
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
            {row.provider && (
              <span>模型: {row.provider}{row.model ? ` / ${row.model}` : ""}</span>
            )}
            {row.duration_sec != null && (
              <span>耗时: {Number(row.duration_sec).toFixed(1)}s</span>
            )}
            {row.task_id && (
              <a href={`/tasks/${row.task_id}`}
                 className="text-[var(--color-accent-blue)] hover:underline">
                源任务
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
