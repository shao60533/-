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
import { TVChart } from "@/components/shared/TVChart"
import { apiGet, apiPost } from "@/lib/api"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface AnalysisDetail {
  id: string; ticker: string; signal: string; date: string
  summary?: string; confidence?: number; risk_level?: string; created_at?: string
  market_report?: string; sentiment_report?: string; news_report?: string
  fundamentals_report?: string; investment_debate?: string
  risk_assessment?: string; trade_decision?: string
  analysts?: Record<string, string>
  advice_json?: string
  // task tracking
  task_id?: string; task_status?: string
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

/** UUID-like = task ID (running); pure digits = analysis_history ID (complete) */
function isTaskId(id: string): boolean {
  return id.length > 10 && /[a-f-]/.test(id)
}

const REPORT_TABS = [
  { key: "summary", label: "概览" },
  { key: "Market", label: "技术面" },
  { key: "Fundamentals", label: "基本面" },
  { key: "Sentiment", label: "情绪面" },
  { key: "News", label: "新闻" },
  { key: "Investment Debate", label: "多空辩论" },
  { key: "Risk Assessment", label: "风险评估" },
] as const

export function AnalysisPage() {
  const [urlId] = useState<string | null>(getIdFromUrl)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Running state: URL has a task UUID
  const [runningTaskId, setRunningTaskId] = useState<string | null>(
    urlId && isTaskId(urlId) ? urlId : null
  )

  // Completed detail ID (numeric)
  const detailId = urlId && !isTaskId(urlId) ? urlId : null

  // Form state
  const [ticker, setTicker] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [submitting, setSubmitting] = useState(false)

  // Load completed analysis
  useEffect(() => {
    if (!detailId) return
    setLoading(true); setError(null)
    apiGet<AnalysisDetail>(`/api/history/${detailId}`)
      .then(setDetail)
      .catch(err => setError(err.message ?? "Failed to load"))
      .finally(() => setLoading(false))
  }, [detailId])

  const handleSubmit = async () => {
    if (!ticker.trim()) return
    setSubmitting(true); setError(null)
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis", params: { ticker: ticker.toUpperCase(), date },
      })
      if (res.task_id) {
        window.location.href = `/analysis/${res.task_id}`
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally { setSubmitting(false) }
  }

  const onRunningComplete = useCallback((analysisId: string) => {
    window.history.replaceState(null, "", `/analysis/${analysisId}`)
    setRunningTaskId(null)
    setLoading(true)
    apiGet<AnalysisDetail>(`/api/history/${analysisId}`)
      .then(setDetail)
      .catch(err => setError(err.message ?? "Failed to load"))
      .finally(() => setLoading(false))
  }, [])

  // ── Running state: show PipelineDAG ─────────────────────────
  if (runningTaskId) {
    return (
      <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/analysis"}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-xl font-bold">分析运行中...</h1>
          <Badge variant="default">运行中</Badge>
        </div>
        <PipelineDAG taskId={runningTaskId} onAllDone={() => {
          // Give backend a moment to save result_ref, then try to find the analysis
          setTimeout(() => {
            apiGet<{ result_ref?: string }>(`/api/tasks/${runningTaskId}`)
              .then(t => {
                const ref = t.result_ref || ""
                const m = ref.match(/(\d+)/)
                if (m) onRunningComplete(m[1])
                else window.location.href = `/tasks/${runningTaskId}`
              })
              .catch(() => window.location.href = `/tasks/${runningTaskId}`)
          }, 1500)
        }} />
        <Card>
          <CardContent className="pt-6 space-y-4">
            <div className="flex gap-2 border-b pb-2">
              {REPORT_TABS.map(t => <Skeleton key={t.key} className="h-6 w-16" />)}
            </div>
            <Skeleton className="h-40" />
          </CardContent>
        </Card>
        <div className="text-center">
          <a href={`/tasks/${runningTaskId}`} className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
            <ExternalLink className="h-3 w-3" /> 查看任务详情
          </a>
        </div>
      </div>
    )
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
      <Card>
        <CardHeader><CardTitle>发起分析</CardTitle></CardHeader>
        <CardContent>
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
          {error && <Alert variant="destructive" className="mt-4"><AlertTitle>提交失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Detail view with TVChart K-line + pipeline + quick-info + 7-tab ── */

function AnalysisDetailView({ detail }: { detail: AnalysisDetail }) {
  const [klineData, setKlineData] = useState<OHLCVRow[]>([])
  const [activeTab, setActiveTab] = useState("summary")
  const tabsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    apiGet<{ data: OHLCVRow[] }>(`/api/chart/${detail.ticker}?period=3mo&interval=1d`)
      .then(r => setKlineData(r.data || []))
      .catch(() => {})
  }, [detail.ticker])

  // Build report content map
  const reportContent: Record<string, string> = {}
  if (detail.summary) reportContent["summary"] = detail.summary
  if (detail.analysts) {
    for (const [key, val] of Object.entries(detail.analysts)) {
      reportContent[key] = typeof val === "string" ? val : JSON.stringify(val, null, 2)
    }
  }

  // Parse advice_json for fundamentals quick-info
  let advice: Record<string, unknown> = {}
  try {
    advice = detail.advice_json
      ? (typeof detail.advice_json === "string" ? JSON.parse(detail.advice_json) : detail.advice_json) as Record<string, unknown>
      : {}
  } catch { /* ignore */ }

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

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
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
          <TVChart data={klineData} height={380} loading={klineData.length === 0} />
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
              return (
                <TabsContent key={tab.key} value={tab.key} className="mt-4">
                  {content ? (
                    <div className="prose prose-invert prose-sm max-w-none text-[var(--color-text-secondary)] max-h-[600px] overflow-y-auto">
                      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground py-8 text-center">暂无数据</p>
                  )}
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
