import { useEffect, useState, useRef, useCallback, lazy, Suspense } from "react"
import {
  Sparkles, Send, ArrowLeft, Clock,
  ExternalLink, ChevronDown, ChevronRight,
  MoreVertical, Trash2, Star,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Switch } from "@/components/ui/switch"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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
import {
  normalizeCardForClient, describeShape,
} from "@/components/analysis/shared/defensive"

interface AnalysisDetail {
  id: string; ticker: string; signal: string; date: string
  summary?: string; confidence?: number; risk_level?: string; created_at?: string
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
  // v1.7 (2026-05-06): structured-summary state machine. Drives the
  // detail-page fallback strategy — when ``rendering_status`` is not
  // ``success``/``partial`` the per-tab area renders the markdown body
  // directly instead of folding it into the debug ``<details>``.
  rendering_status?: "success" | "partial" | "failed" | "empty" | "pending" | null
  rendering_error?: string | null
  rendering_generated_at?: string | null
  rendering_available_tabs?: string[] | null
  // v1.20: canonical trade action parsed from ``trade_decision`` text.
  // Always prefer ``decision_action`` over ``signal`` when present —
  // ``signal_mismatch=true`` means the stored signal disagreed with the
  // trader's explicit ``FINAL TRANSACTION PROPOSAL: **X**`` (legacy row;
  // we surface a small "已校正" hint so the user knows we corrected it).
  decision_action?: "Buy" | "Sell" | "Hold" | null
  signal_mismatch?: boolean
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

// v2.1 (2026-05-07) — depth ladder collapsed to a 2-state UX. The
// backend still accepts ``depth ∈ {quick, standard, deep}`` for
// idempotency / paper-trade replay, but the frontend only ever
// surfaces "标准" / "深度". Legacy ``quick`` rows display as "标准"
// — the user no longer needs a separate "30s skip-debate" mode now
// that "deep" is the only meaningful upsell.
type AnalysisDepth = "standard" | "deep"

function depthLabel(d: string | null | undefined): string {
  // Legacy ``quick`` rows from earlier releases collapse to "标准"
  // per the v2.1 product decision — there's no longer a user-visible
  // "快速" mode and surfacing it would suggest the option still
  // exists.
  switch ((d || "").toLowerCase()) {
    case "deep":     return "深度"
    case "standard": return "标准"
    case "quick":    return "标准"  // legacy alias — see comment above
    default:         return "标准"
  }
}

interface OHLCVRow {
  date: string; open: number; high: number; low: number; close: number; volume: number
}

// mobile-ui-v1.3: NewsItem + fundNum/fmtNum/fmtPct used to power the
// QuickInfoCard tiles (news / fundamentals / debate). Cards were
// removed; news + fundamentals continue to render inside the
// structured "新闻" / "基本面" tabs via the cards barrel.

interface TaskSubmitResult { task_id: string; status: string }

function signalVariant(signal: string): "buy" | "sell" | "hold" | "default" {
  const s = signal?.toLowerCase() ?? ""
  if (s.includes("buy") || s.includes("bullish")) return "buy"
  if (s.includes("sell") || s.includes("bearish")) return "sell"
  if (s.includes("hold") || s.includes("neutral")) return "hold"
  return "default"
}

/** v1.3 — Unify the long tail of LLM signal strings ("Overweight" /
 *  "Strong Sell" / "BUY" / "bullish" / 中文 / ...) into a 3-state
 *  user-facing label. ``signalVariant`` keeps owning badge color
 *  (4 variants); this helper only owns displayed text. Sell first
 *  so "underweight" doesn't slip into the buy branch. */
export function signalLabel(signal: string | null | undefined): "Buy" | "Sell" | "Hold" {
  const s = (signal ?? "").toLowerCase().trim()
  if (!s) return "Hold"
  if (
    s.includes("sell") || s.includes("bearish")
    || s.includes("underweight") || s.includes("减仓")
    || s === "reduce"
  ) return "Sell"
  if (
    s.includes("buy") || s.includes("bullish")
    || s.includes("overweight") || s.includes("加仓")
    || s === "add"
  ) return "Buy"
  return "Hold"
}

function getIdFromUrl(): string | null {
  const match = window.location.pathname.match(/\/analysis\/([^/]+)/)
  return match?.[1] ?? null
}

/** UUID = task ID (running state); pure digits or "analysis_history:N" = completed history ID */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function isTaskId(id: string): boolean {
  return UUID_RE.test(id)
}

// mobile-ui-v1.3: structured tabs labels collapse to 1-2 chars so the
// strict 8-tab assertion (TC-MUI-A5) reads cleanly on 375px without the
// chip row going multi-line.
const REPORT_TABS = [
  { key: "summary", label: "概览" },
  { key: "Market", label: "市场" },
  { key: "Sentiment", label: "情绪" },
  { key: "News", label: "新闻" },
  { key: "Fundamentals", label: "基本面" },
  { key: "Investment Debate", label: "辩论" },
  { key: "Risk Assessment", label: "风险" },
  { key: "Decision", label: "决策" },
] as const

// v2.1 — DEPTH_OPTIONS removed. UI is now a single ``开启深度分析``
// switch (see the form below); the wire still uses ``depth: "standard"
// | "deep"`` so the worker / paper-trade replay don't have to migrate.

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
  // v2.1 — single boolean form input ("开启深度分析"). Wire-encoded
  // to the legacy ``depth`` field on submit so the worker keeps its
  // existing dispatch path.
  const [deepAnalysis, setDeepAnalysis] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // v1.22 unified inbox: in-flight tasks + completed analyses in one
  // list. Replaces the old "最近分析" 5-card strip + the standalone
  // /history page.
  const [inbox, setInbox] = useState<InboxRow[]>([])
  const [runningTotal, setRunningTotal] = useState(0)
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
    // v2.1 — wire-encode the boolean toggle. Backend still expects
    // ``depth ∈ {standard, deep}``; ``deep_analysis`` is shipped as a
    // hint for any future consumer that wants the canonical UI flag.
    const wireDepth: AnalysisDepth = deepAnalysis ? "deep" : "standard"
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis",
        params: {
          ticker: submittedTicker,
          date,
          depth: wireDepth,
          deep_analysis: deepAnalysis,
        },
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
          depth: wireDepth,
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

  // After a task settles (websocket task_completed/task_failed for one
  // of our running rows), pull a fresh inbox so the row flips from
  // "运行中" to a completed analysis card. socket.io is lazy-imported
  // (matches the pattern used by the running-view subscription below)
  // so the inbox view doesn't pay for it on first paint.
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
          if (env.event === "task_completed" || env.event === "task_failed") {
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
  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Sparkles className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">AI 分析</h1>
      </div>

      {/* v1.3.1 R-MUI-22: 发起分析 form is the high-frequency entry
          point on mobile, so it sits ABOVE the inbox. Submit-then-
          watch flow stays intact — the optimistic running row still
          shows up in the inbox below as soon as the user submits. */}
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

          {/* v2.1 — single switch replaces the 3-card depth ladder.
              Labels stay short on mobile; the descriptive hint sits
              under the switch row so 320px doesn't get crammed. */}
          <div className="rounded-lg border border-border p-3 flex items-center gap-3 min-w-0">
            <div className="flex-1 min-w-0">
              <label
                htmlFor="analysis-deep-switch"
                className="text-sm font-medium block cursor-pointer"
              >
                开启深度分析
              </label>
              <p className="text-xs text-muted-foreground mt-0.5 break-words">
                {deepAnalysis
                  ? "深度分析：~5min · 启用迭代反思 · 适合关键决策"
                  : "标准分析：~2min · 7 Agent 默认管线"}
              </p>
            </div>
            <Switch
              id="analysis-deep-switch"
              checked={deepAnalysis}
              onCheckedChange={setDeepAnalysis}
              className="shrink-0"
            />
          </div>

          {error && <Alert variant="destructive" className="mt-2"><AlertTitle>提交失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        </CardContent>
      </Card>

      {/* v1.22 unified inbox: running tasks + completed analyses in
          one list. Replaces the standalone /history page; /history now
          301-redirects here. Inline ``PipelineDAG`` for running rows
          gives users live progress without leaving the page. */}
      <Card>
        <CardHeader className="pb-2">
          <div className="mobile-card-header">
            <CardTitle className="mc-title text-sm truncate">分析记录</CardTitle>
            {/* mobile-ui-v1.3: standalone "Inbox 工具" tray (refresh /
                filter / 看任务) removed. Inbox auto-refreshes via the
                websocket subscription whenever a tracked task settles. */}
            <div className="mc-actions">
              {runningTotal > 0 && (
                <Badge variant="default" className="text-[10px]">
                  <Clock className="h-3 w-3 mr-1 animate-spin" />
                  {runningTotal} 运行中
                </Badge>
              )}
            </div>
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
              暂无分析记录，提交上方的新分析开始
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

function AnalysisDetailView({ detail: initialDetail }: { detail: AnalysisDetail }) {
  // v1.7 — local mirror so the structured-summary retry banner can
  // re-fetch ``/api/history/<id>`` after the backfill task settles
  // and swap in the freshly-rendered cards without a full page
  // reload. Initial value is the prop the parent fetched.
  const [detail, setDetail] = useState<AnalysisDetail>(initialDetail)
  useEffect(() => { setDetail(initialDetail) }, [initialDetail])
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

  // 2026-05-04 mobile: shrink the K-line from 380→260px on ≤575.98px
  // so the chart doesn't push the 8-tab report below the fold. Re-
  // measure on resize to handle device rotation cleanly.
  const [kChartHeight, setKChartHeight] = useState<number>(() =>
    typeof window !== "undefined"
      && window.matchMedia?.("(max-width: 575.98px)").matches
      ? 260
      : 380,
  )
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const mql = window.matchMedia("(max-width: 575.98px)")
    const apply = () => setKChartHeight(mql.matches ? 260 : 380)
    apply()
    mql.addEventListener?.("change", apply)
    return () => mql.removeEventListener?.("change", apply)
  }, [])

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

  // Parse advice_json so the catch suppresses bad rows. We only need the
  // side effect of validating it parses; the rendered UI reads structured
  // fields directly, not this blob.
  try {
    if (detail.advice_json && typeof detail.advice_json === "string") {
      JSON.parse(detail.advice_json)
    }
  } catch { /* ignore malformed advice payloads */ }

  // mobile-ui-v1.3: Quick Info cards (news / fundamentals / debate)
  // were removed. News + fundamentals continue to render inside the
  // structured "新闻" / "基本面" tabs via the cards barrel.

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
      {/* Header — mobile-ui-v1.3: no top conclusion card, no Quick Info,
          no stats grid. The structured 8-tab core IS the first business
          section. The header keeps just the back button + ticker badge. */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => window.location.href = "/analysis"}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-xl font-bold font-mono">{detail.ticker}</h1>
        <Badge variant={signalVariant(canonicalSignal(detail))}>
          {signalLabel(canonicalSignal(detail))}
        </Badge>
        {detail.signal_mismatch && (
          <span
            className="text-[10px] text-amber-400"
            title={`原存储信号: ${detail.signal} · 决策正文: ${detail.decision_action}`}
          >
            信号已按最终决策校正
          </span>
        )}
        {detail.confidence != null && (
          <span className="text-sm text-muted-foreground">置信度 {(detail.confidence * 100).toFixed(0)}%</span>
        )}
      </div>

      {actionMsg && (
        <div className="text-xs text-muted-foreground">{actionMsg}</div>
      )}

      {/* Pipeline DAG (shown only for live running tasks). */}
      {isRunning && detail.task_id && (
        <PipelineDAG taskId={detail.task_id} onAllDone={() => window.location.reload()} />
      )}

      {/* v1.7 — structured-summary status banner. Shows up between the
          actions row and the tabs when extraction failed/empty/pending
          so the user sees WHY the cards aren't showing and can retry
          with one click. ``success`` and ``partial`` skip the banner —
          partial still has the cards that did render plus markdown
          fallback for the others, no banner needed. */}
      <RenderingStatusBanner detail={detail} onRetried={() => {
        // Re-pull the detail after the backfill task finishes so the
        // structured cards swap in. Detail is fetched once on mount;
        // we do a quick re-fetch here without remounting the page.
        apiGet<AnalysisDetail>(`/api/history/${detail.id}`).then(setDetail).catch(() => {})
      }} />

      {/* Structured analysis core — first business section of the
          detail view per mobile-ui-v1.3 §4.3. Strict 8 tabs, no "原文"
          tab. The Markdown body still appears as a per-tab <details>
          fallback inside each tab when a structured card is available. */}
      <Card ref={tabsRef} data-section="structured-core">
        <CardHeader>
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <CardTitle className="text-sm">结构化分析核心</CardTitle>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => handleExport("md")}>导出 MD</Button>
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
        </CardHeader>
        <CardContent className="pt-2">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList
              data-analysis-structured-tabs=""
              className="w-full justify-start bg-transparent border-b rounded-none pb-0 gap-0"
            >
              {REPORT_TABS.map(tab => (
                <TabsTrigger key={tab.key} value={tab.key}
                  className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-3 pb-2">
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {REPORT_TABS.map(tab => {
              const rawStruct = detail.rendering?.[tab.key as keyof RenderingDict]
              const struct = rawStruct
                ? normalizeCardForClient(tab.key, rawStruct)
                : null
              const hasStruct = !!struct
              return (
                <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
                  {hasStruct ? (
                    <ErrorBoundary
                      resetKey={`${detail.id}:${tab.key}`}
                      onError={(err) => {
                        // eslint-disable-next-line no-console
                        console.error("[analysis card] render failed", {
                          analysis_id: detail.id,
                          tab_key: tab.key,
                          error_name: err.name,
                          error_message: err.message,
                          struct_shape: describeShape(struct),
                        })
                      }}
                      fallback={({ error }) => (
                        <CardFallback error={error} />
                      )}
                    >
                      <Suspense fallback={<Skeleton className="h-32 w-full" />}>
                        <AnalysisCards tabKey={tab.key} data={struct} />
                      </Suspense>
                    </ErrorBoundary>
                  ) : (
                    <p className="text-sm text-muted-foreground py-8 text-center">
                      暂无结构化数据，底部原始报告可作为 fallback 查看。
                    </p>
                  )}
                </TabsContent>
              )
            })}
          </Tabs>
        </CardContent>
      </Card>

      {/* K-line chart — placed AFTER the structured core per the demo
          IA. Viewport-gated: TVChart is lazy-loaded only after the
          section scrolls into view, and the OHLCV fetch fires from
          the same observer. */}
      <Card ref={klineSectionRef}>
        <CardHeader><CardTitle className="text-sm">K 线走势（近 3 个月）</CardTitle></CardHeader>
        <CardContent>
          {klineVisible ? (
            <Suspense fallback={<Skeleton className="w-full" style={{ height: kChartHeight }} />}>
              <TVChart data={klineData} state={klineState} onRetry={refetchKline} height={kChartHeight} />
            </Suspense>
          ) : (
            <Skeleton className="w-full" style={{ height: kChartHeight }} />
          )}
        </CardContent>
      </Card>

      {/* 记录与操作 — metadata + secondary actions. Sits AFTER K线
          per mobile-ui-v1.3 §4.3, replacing the old top action row. */}
      <Card data-section="records">
        <CardHeader><CardTitle className="text-sm">记录与操作</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 gap-x-3 gap-y-1 text-xs min-w-0">
            <div className="min-w-0">
              <span className="text-muted-foreground">日期</span>
              <div className="font-mono truncate">{detail.date || "—"}</div>
            </div>
            <div className="min-w-0">
              <span className="text-muted-foreground">风险</span>
              <div className="truncate">{detail.risk_level || "—"}</div>
            </div>
            <div className="min-w-0">
              <span className="text-muted-foreground">深度</span>
              <div className="truncate">{depthLabel(detail.depth)}</div>
            </div>
          </div>
          {(detail.created_by_name || detail.provider || detail.duration_sec != null || detail.created_at) && (
            <div className="text-[11px] text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
              {detail.created_by_name && <span>创建者：{detail.created_by_name}</span>}
              {detail.provider && (
                <span>Provider：{detail.provider}{detail.model ? ` / ${detail.model}` : ""}</span>
              )}
              {detail.duration_sec != null && (
                <span>耗时：{Number(detail.duration_sec).toFixed(1)}s</span>
              )}
              {detail.created_at && <span>创建于：{detail.created_at}</span>}
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={handleReanalyze}>再次分析</Button>
            <Button variant="outline" size="sm" onClick={handleTrack}>加入观察</Button>
            <Button
              size="sm"
              onClick={handlePaperTrack}
              disabled={paperBusy}
            >
              {paperBusy ? "提交中…" : "纸面交易"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 原始报告 fallback / debug — chip switcher exposes the raw
          analyst markdown panels (Markdown / 市场原文 / 新闻原文 /
          风险原文) for cases where the structured cards above are
          missing or the user wants the source text. */}
      <RawReportFallback detail={detail} />
    </div>
  )
}

/* ── Raw report fallback ─────────────────────────────────── */

const RAW_TABS = [
  { key: "markdown",      label: "Markdown" },
  { key: "market",        label: "市场原文" },
  { key: "news",          label: "新闻原文" },
  { key: "risk",          label: "风险原文" },
] as const

type RawTabKey = typeof RAW_TABS[number]["key"]

function RawReportFallback({ detail }: { detail: AnalysisDetail }) {
  const [tab, setTab] = useState<RawTabKey>("markdown")

  const content = (() => {
    switch (tab) {
      case "market": return detail.market_report || ""
      case "news":   return detail.news_report || ""
      case "risk":   return detail.risk_assessment || ""
      case "markdown":
      default: {
        // Concatenate the analyst sections so the Markdown chip shows
        // a single readable document; falls back to the summary when
        // analyst-level reports are absent.
        const parts = [
          detail.summary,
          detail.market_report,
          detail.sentiment_report,
          detail.news_report,
          detail.fundamentals_report,
          detail.investment_debate,
          detail.risk_assessment,
          detail.trade_decision,
        ].filter(Boolean) as string[]
        return parts.join("\n\n---\n\n")
      }
    }
  })()

  return (
    <Card data-section="raw-report">
      <CardHeader>
        <CardTitle className="text-sm">原始报告 <span className="text-xs text-muted-foreground ml-2">fallback / debug</span></CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2 flex-wrap">
          {RAW_TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 rounded text-xs border transition-colors ${
                tab === t.key
                  ? "bg-primary/10 text-primary border-primary/40"
                  : "border-border text-muted-foreground hover:border-border/80"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {content ? (
          <div className="prose prose-invert prose-sm max-w-none text-[var(--color-text-secondary)] max-h-[400px] overflow-y-auto">
            <Suspense fallback={<Skeleton className="h-24 w-full" />}>
              <MarkdownBody>{content}</MarkdownBody>
            </Suspense>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground py-4 text-center">该面无原始内容</p>
        )}
      </CardContent>
    </Card>
  )
}

/* ── Fallback used when a structured card render throws ───── */

/** Per-tab fallback shown when ``AnalysisCards`` throws inside the
 *  ErrorBoundary. The user-facing copy is intentionally generic — a
 *  structured-card failure is not actionable for end users; the
 *  Markdown ``<details>`` below this fallback always renders the full
 *  analyst body so users still see the conclusion. The expandable
 *  ``<details>`` underneath reveals the error name+message so an
 *  operator (or developer hitting F12) can diagnose without leaving
 *  the page; we do NOT print the error stack or struct payload — that
 *  goes to ``console.error`` where it's filterable. */
function CardFallback({ error }: { error: Error }) {
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
      <div>结构化摘要暂不可用，已显示完整论述。</div>
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

/* ── Rendering status banner ───────────────────────────────── */

/**
 * v1.7 — show when the structured-summary state machine is anything
 * other than ``success`` / ``partial``. Offers a one-click retry that
 * enqueues the ``analysis_rendering_backfill`` task; on completion
 * the parent re-fetches ``/api/history/<id>`` and the cards swap in.
 *
 * ``partial`` is intentionally NOT a banner case: the cards that did
 * render are real value, the missing tabs already fall back to
 * markdown directly, and an extra banner adds noise without action.
 */
function RenderingStatusBanner({
  detail, onRetried,
}: {
  detail: AnalysisDetail
  onRetried: () => void
}) {
  const status = detail.rendering_status
  const [retrying, setRetrying] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const handleRetry = async () => {
    setRetrying(true); setMsg(null)
    try {
      await apiPost(`/api/history/${detail.id}/rendering/retry`, {})
      setMsg("已提交重试任务，约 30 秒后刷新查看")
      // Give the backend ~30s to finish the backfill, then bounce.
      window.setTimeout(() => { onRetried() }, 30_000)
    } catch (err: unknown) {
      setMsg(err instanceof Error ? `重试失败：${err.message}` : "重试失败")
    } finally {
      setRetrying(false)
    }
  }

  // Skip rendering for healthy + partial states.
  if (!status || status === "success" || status === "partial") return null

  const headline =
    status === "failed"  ? "结构化摘要生成失败" :
    status === "pending" ? "结构化摘要待生成" :
    /* empty */          "未生成结构化摘要"
  const tone = status === "failed"
    ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
    : "border-zinc-500/40 bg-zinc-500/5 text-zinc-300"

  return (
    <div className={`rounded border px-3 py-2 text-xs flex flex-wrap items-start gap-2 ${tone}`}>
      <div className="flex-1 min-w-0">
        <div className="font-semibold">{headline}</div>
        <div className="opacity-80 mt-0.5 break-words">
          {status === "failed"
            ? "完整论述已显示在下方各 tab，可点击重试重新生成结构化卡片。"
            : status === "empty"
            ? "本次分析没有结构化卡片（历史记录尚未生成）。可点击重试按当前数据补一份。"
            : "结构化摘要任务正在排队，稍候自动出现；也可手动触发重试。"}
        </div>
        {detail.rendering_error && (
          <details className="mt-1">
            <summary className="cursor-pointer text-[10px] opacity-70">
              错误详情（开发者）
            </summary>
            <code className="block mt-1 text-[10px] font-mono whitespace-pre-wrap opacity-70 break-words">
              {detail.rendering_error}
            </code>
          </details>
        )}
        {msg && (
          <div className="mt-1 text-[11px] opacity-90">{msg}</div>
        )}
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={handleRetry}
        disabled={retrying}
        className="shrink-0"
      >
        {retrying ? "提交中…" : "重新生成结构化摘要"}
      </Button>
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
    <div className="flex flex-wrap items-center gap-2 pb-2 border-b border-border/40 min-w-0">
      <div className="relative flex-1 min-w-0 max-w-xs">
        <Input
          value={ticker}
          onChange={e => onTicker(e.target.value.toUpperCase())}
          placeholder="按股票代码筛选"
          className="h-8 text-sm"
        />
      </div>
      <span className="text-xs text-muted-foreground sm:ml-auto shrink-0">
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
        <span className="text-xs text-muted-foreground sm:ml-auto shrink-0">
          {fmtRelative(row.submitted_at)}
        </span>
        {!isFailure && (
          <Button
            variant="ghost" size="sm"
            onClick={() => setCollapsed(c => !c)}
            title={collapsed ? "展开管线" : "折叠管线"}
            className="h-6 px-1.5 shrink-0"
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
      className="rounded border border-border/50 bg-card/40 hover:border-primary/40 transition-colors min-w-0 overflow-hidden"
    >
      {/* v2.1 — 3-row layout that survives 320/375/414 widths.
          Row A = chevron + ticker + signal | bookmark + open + ⋯ menu
          Row B = depth badge + date + relative time + (creator on sm+)
          Action menu (删除) lives inside the dropdown so we never
          render free-floating "删除" text on mobile. */}
      <div className="px-3 py-2 text-sm space-y-1 min-w-0">
        {/* Row A — primary identity + per-row actions */}
        <div
          onClick={toggle}
          className="flex items-center gap-2 cursor-pointer min-w-0"
        >
          {expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
          <span className="font-mono font-semibold truncate min-w-0">{row.ticker}</span>
          <Badge variant={signalVariant(row.signal || "")} className="text-[10px] shrink-0">
            {signalLabel(row.signal)}
          </Badge>
          {/* Right-edge action cluster — pinned with ml-auto so it
              never wraps under the ticker on narrow screens. ``shrink-0``
              keeps the cluster intact when the truncated ticker tries
              to claim more width. */}
          <div className="ml-auto flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={toggleBookmark}
              disabled={busy}
              className={
                "p-1.5 rounded hover:bg-muted/40 transition-colors " +
                (bookmarked ? "text-amber-400" : "text-muted-foreground")
              }
              title={bookmarked ? "取消收藏" : "收藏"}
              aria-label={bookmarked ? "取消收藏" : "收藏"}
            >
              <Star
                className={"h-4 w-4 " + (bookmarked ? "fill-current" : "")}
              />
            </button>
            <a
              href={`/analysis/${row.id}`}
              onClick={e => e.stopPropagation()}
              className="p-1.5 rounded hover:bg-muted/40 text-[var(--color-accent-blue)] transition-colors"
              title="打开详情"
              aria-label="打开详情"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
            <DropdownMenu>
              <DropdownMenuTrigger asChild onClick={e => e.stopPropagation()}>
                <button
                  type="button"
                  className="p-1.5 rounded hover:bg-muted/40 text-muted-foreground transition-colors"
                  title="更多操作"
                  aria-label="更多操作"
                >
                  <MoreVertical className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={() => remove({ stopPropagation: () => {} } as React.MouseEvent)}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-2" />删除记录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {/* Row B — secondary metadata. ``flex-wrap`` allows graceful
            stacking when both date + creator + relative time can't
            fit on one line at 320px. */}
        <div
          onClick={toggle}
          className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground cursor-pointer min-w-0"
        >
          <Badge variant="muted" className="text-[10px] shrink-0">
            {depthLabel(row.depth)}
          </Badge>
          <span className="shrink-0">{row.date}</span>
          <span className="shrink-0">{fmtRelative(row.created_at)}</span>
          {row.created_by_name && (
            <span className="hidden sm:inline truncate min-w-0">
              · {row.created_by_name}
            </span>
          )}
        </div>
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
