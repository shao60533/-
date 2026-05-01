import { useEffect, useState, useRef, useCallback } from "react"
import { Sparkles, Send, ArrowLeft, Clock, Newspaper, BarChart3, Scale, ExternalLink } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PipelineDAG } from "@/components/shared/PipelineDAG"
import { TVChart, type TVChartState } from "@/components/shared/TVChart"
import { apiGet, apiPost } from "@/lib/api"
import { subscribeTaskStream } from "@/lib/socket"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import {
  OverviewCard, MarketCard, SentimentCard, NewsCard,
  FundamentalsCard, DebateCard, RiskCard, DecisionCard,
  type RenderingDict,
} from "@/components/analysis"

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
}

// Map tab key → structured card component. Each card narrows ``data`` to
// its own schema-shaped type internally; we type the registry as ``any``
// here because TypeScript can't pin a polymorphic per-key type cleanly.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TAB_CARD: Record<string, React.FC<{ data: any }>> = {
  "summary":            OverviewCard,
  "Market":             MarketCard,
  "Sentiment":          SentimentCard,
  "News":               NewsCard,
  "Fundamentals":       FundamentalsCard,
  "Investment Debate":  DebateCard,
  "Risk Assessment":    RiskCard,
  "Decision":           DecisionCard,
}

interface RecentAnalysisRow {
  id: number; ticker: string; signal: string; date: string
  created_at?: string; created_by_name?: string | null
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

interface OHLCVRow {
  date: string; open: number; high: number; low: number; close: number; volume: number
}

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

// rehype-sanitize schema. Default is GitHub's safe-list; we extend it to
// keep tables + fenced code rendering (LLM output frequently uses both)
// without enabling raw HTML or scripts. Anything not on this list is
// stripped before React inserts the markdown into the DOM.
const MD_SANITIZE_SCHEMA = {
  ...defaultSchema,
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    code: [...(defaultSchema.attributes?.code ?? []), "className"],
    span: [...(defaultSchema.attributes?.span ?? []), "className"],
    div: [...(defaultSchema.attributes?.div ?? []), "className"],
  },
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "table", "thead", "tbody", "tr", "th", "td",
    "code", "pre",
  ],
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

export function AnalysisPage() {
  const [urlId] = useState<string | null>(getIdFromUrl)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Running-state: when URL has a task UUID
  const [taskId, setTaskId] = useState<string | null>(
    urlId && isTaskId(urlId) ? urlId : null
  )
  const [taskTicker, setTaskTicker] = useState<string>("")

  // Form state
  const [ticker, setTicker] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [depth, setDepth] = useState<AnalysisDepth>("standard")
  const [submitting, setSubmitting] = useState(false)
  // Recent shared-research cards on the form page (top 5).
  const [recent, setRecent] = useState<RecentAnalysisRow[]>([])

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
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis",
        params: { ticker: ticker.toUpperCase(), date, depth },
      })
      // Navigate to /analysis/<task_id> to show running DAG
      if (res.task_id) {
        window.history.replaceState(null, "", `/analysis/${res.task_id}`)
        setTaskId(res.task_id)
        setTaskTicker(ticker.toUpperCase())
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally { setSubmitting(false) }
  }

  // Pull the top 5 most recent analyses for the form-page "最近分析" cards.
  // Only fired on the form view (no detailId, no taskId) to avoid wasted
  // bandwidth on the detail / running screens.
  useEffect(() => {
    if (detailId || taskId) return
    apiGet<{ items?: RecentAnalysisRow[]; records?: RecentAnalysisRow[] }>(
      "/api/history?limit=5",
    )
      .then((r) => {
        const items = r.items ?? r.records ?? []
        setRecent(items.slice(0, 5))
      })
      .catch(() => setRecent([]))
  }, [detailId, taskId])

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

      {recent.length > 0 && (
        <div>
          <div className="text-sm font-semibold mb-2">最近分析</div>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-5">
            {recent.map((a) => (
              <a
                key={a.id}
                href={`/analysis/${a.id}`}
                className="rounded-lg border border-border bg-card hover:border-primary/40 transition-colors p-3 block"
              >
                <div className="font-mono text-base font-bold">{a.ticker}</div>
                <div className="mt-1">
                  <Badge variant={signalVariant(a.signal || "")} className="text-[10px]">
                    {a.signal || "—"}
                  </Badge>
                </div>
                <div className="mt-2 text-xs text-muted-foreground truncate">
                  {a.created_by_name ?? "—"}
                </div>
                <div className="text-xs text-muted-foreground">{a.date}</div>
              </a>
            ))}
          </div>
        </div>
      )}

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
    const sub = subscribeTaskStream({
      taskIds: [taskId],
      onEvent: (env) => {
        if (env.event === "task_completed") {
          setCompleted(true)
          // Extract analysis_id from result_ref
          const ref = (env.payload as any)?.result_ref ?? ""
          const m = ref.match?.(/(\d+)/)
          if (m) {
            setTimeout(() => onComplete(m[1]), 1000)
          }
        }
      },
      onStatusChange: () => {},
    })
    return () => sub.destroy()
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

  useEffect(() => {
    refetchKline()
  }, [refetchKline])

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

  // Quick-info extractions
  const newsSnippet = (reportContent["News"] || "").slice(0, 200)
  const fundSnippet = extractFundamentals(reportContent["Fundamentals"] || "")
  const debateSnippet = extractDebateCount(reportContent["Investment Debate"] || "")

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
          <Badge variant={signalVariant(detail.signal)}>{detail.signal || "N/A"}</Badge>
          {detail.confidence != null && (
            <span className="text-sm text-muted-foreground">置信度 {(detail.confidence * 100).toFixed(0)}%</span>
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

      {/* Stats row */}
      <div className="grid gap-4 md:grid-cols-3 grid-collapse-mobile">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">分析日期</CardTitle></CardHeader>
          <CardContent className="text-lg font-mono">{detail.date}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">信号</CardTitle></CardHeader>
          <CardContent><Badge variant={signalVariant(detail.signal)} className="text-sm">{detail.signal || "N/A"}</Badge></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">风险等级</CardTitle></CardHeader>
          <CardContent className="text-lg">{detail.risk_level || "-"}</CardContent>
        </Card>
      </div>

      {/* Quick-info cards (news / fundamentals / debate) */}
      <div className="grid gap-4 md:grid-cols-3 grid-collapse-mobile">
        <QuickInfoCard
          icon={<Newspaper className="h-4 w-4" />}
          title="最近新闻"
          snippet={newsSnippet || "暂无新闻数据"}
          onClick={() => scrollToTab("News")}
        />
        <QuickInfoCard
          icon={<BarChart3 className="h-4 w-4" />}
          title="基本面指标"
          snippet={fundSnippet || "暂无基本面数据"}
          onClick={() => scrollToTab("Fundamentals")}
        />
        <QuickInfoCard
          icon={<Scale className="h-4 w-4" />}
          title="多空辩论"
          snippet={debateSnippet || "暂无辩论数据"}
          onClick={() => scrollToTab("Investment Debate")}
        />
      </div>

      {/* K-line chart (TradingView lightweight-charts) */}
      <Card>
        <CardHeader><CardTitle className="text-sm">K 线走势（近 3 个月）</CardTitle></CardHeader>
        <CardContent>
          <TVChart data={klineData} state={klineState} onRetry={refetchKline} height={380} />
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
              const struct = detail.rendering?.[tab.key as keyof RenderingDict]
              const CardComp = TAB_CARD[tab.key]
              const hasStruct = !!struct && !!CardComp
              return (
                <TabsContent key={tab.key} value={tab.key} className="mt-4 space-y-4">
                  {hasStruct ? (
                    /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
                    <CardComp data={struct as any} />
                  ) : null}
                  {content ? (
                    <details className="rounded border border-border/50">
                      <summary className="cursor-pointer px-4 py-2 text-xs text-muted-foreground hover:bg-muted/30">
                        {hasStruct ? "完整论述（点击展开）" : "完整论述"}
                      </summary>
                      <div className="prose prose-invert prose-sm max-w-none px-4 py-3 max-h-[600px] overflow-y-auto text-[var(--color-text-secondary)]">
                        <Markdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[[rehypeSanitize, MD_SANITIZE_SCHEMA]]}
                        >
                          {content}
                        </Markdown>
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

/* ── Quick-info card ─────────────────────────────────────── */

function QuickInfoCard({ icon, title, snippet, onClick }: {
  icon: React.ReactNode; title: string; snippet: string; onClick: () => void
}) {
  return (
    <Card className="cursor-pointer hover:border-primary/30 transition-colors" onClick={onClick}>
      <CardContent className="pt-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[var(--color-accent-blue)]">{icon}</span>
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</span>
        </div>
        <p className="text-xs text-[var(--color-text-secondary)] line-clamp-3 leading-relaxed">
          {snippet}
        </p>
        <span className="text-[10px] text-[var(--color-accent-blue)] mt-2 inline-block">查看详情 →</span>
      </CardContent>
    </Card>
  )
}

/* ── Helpers ──────────────────────────────────────────────── */

function extractFundamentals(text: string): string {
  // Try to extract PE, ROE, D/E from fundamentals report text
  const pe = text.match(/PE[^:：]*[:：]\s*([\d.]+)/i)?.[1]
  const roe = text.match(/ROE[^:：]*[:：]\s*([\d.]+%?)/i)?.[1]
  const de = text.match(/D\/E[^:：]*[:：]\s*([\d.]+)/i)?.[1]
  const parts: string[] = []
  if (pe) parts.push(`PE: ${pe}`)
  if (roe) parts.push(`ROE: ${roe}`)
  if (de) parts.push(`D/E: ${de}`)
  if (parts.length > 0) return parts.join(" · ")
  return text.slice(0, 150)
}

function extractDebateCount(text: string): string {
  const bull = (text.match(/看多|bullish|买入|buy/gi) || []).length
  const bear = (text.match(/看空|bearish|卖出|sell/gi) || []).length
  if (bull === 0 && bear === 0) return text.slice(0, 150)
  return `看多论点 ${bull} 个 · 看空论点 ${bear} 个`
}
