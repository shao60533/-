import { useEffect, useState, useMemo } from "react"
import { Sparkles, Send, ArrowLeft, Clock } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ChartPanel } from "@/components/shared/ChartPanel"
import type { EChartsOption } from "@/lib/echarts"
import { apiGet, apiPost } from "@/lib/api"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface AnalysisDetail {
  id: string; ticker: string; signal: string; date: string
  summary?: string; confidence?: number; risk_level?: string; created_at?: string
  // 7 report fields
  market_report?: string; sentiment_report?: string; news_report?: string
  fundamentals_report?: string; investment_debate?: string
  risk_assessment?: string; trade_decision?: string
  analysts?: Record<string, string>
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

// Tab config mapping API field keys to display labels
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
  const [detailId] = useState<string | null>(getIdFromUrl)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [ticker, setTicker] = useState("")
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<TaskSubmitResult | null>(null)

  useEffect(() => {
    if (!detailId) return
    setLoading(true)
    setError(null)
    apiGet<AnalysisDetail>(`/api/history/${detailId}`)
      .then(setDetail)
      .catch(err => setError(err.message ?? "Failed to load"))
      .finally(() => setLoading(false))
  }, [detailId])

  const handleSubmit = async () => {
    if (!ticker.trim()) return
    setSubmitting(true); setError(null); setSubmitResult(null)
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis", params: { ticker: ticker.toUpperCase(), date },
      })
      setSubmitResult(res)
      if (res.task_id) setTimeout(() => { window.location.href = "/tasks" }, 800)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally { setSubmitting(false) }
  }

  // Loading / error / detail / form
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

  // Submit form
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
          {submitResult && (
            <Alert variant="success" className="mt-4">
              <AlertTitle>任务已提交</AlertTitle>
              <AlertDescription>
                任务 ID: <code className="font-mono">{submitResult.task_id}</code>，状态: {submitResult.status}。
                <a href="/tasks" className="ml-2 text-[var(--color-accent-blue)] hover:underline">查看任务进度</a>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Analysis Detail with K-line + 7-tab reports ───────────── */

function AnalysisDetailView({ detail }: { detail: AnalysisDetail }) {
  const [klineData, setKlineData] = useState<OHLCVRow[]>([])

  useEffect(() => {
    apiGet<{ data: OHLCVRow[] }>(`/api/chart/${detail.ticker}?period=3mo&interval=1d`)
      .then(r => setKlineData(r.data || []))
      .catch(() => {})
  }, [detail.ticker])

  // K-line chart option
  const klineOption = useMemo((): EChartsOption | null => {
    if (klineData.length === 0) return null
    const dates = klineData.map(r => r.date)
    const ohlc = klineData.map(r => [r.open, r.close, r.low, r.high])
    const volumes = klineData.map(r => r.volume)

    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { trigger: "axis", backgroundColor: "#1c2128", borderColor: "rgba(56,130,255,0.12)", textStyle: { color: "#e6edf3" } },
      grid: [{ left: 60, right: 20, top: 30, height: "58%" }, { left: 60, right: 20, top: "76%", height: "16%" }],
      xAxis: [
        { type: "category", data: dates, gridIndex: 0, axisLine: { lineStyle: { color: "#444" } } },
        { type: "category", data: dates, gridIndex: 1, axisLine: { lineStyle: { color: "#444" } } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: "#222" } } },
        { scale: true, gridIndex: 1, splitLine: { show: false } },
      ],
      series: [
        {
          name: "K线", type: "candlestick", data: ohlc,
          itemStyle: { color: "#00ff88", color0: "#ff3860", borderColor: "#00ff88", borderColor0: "#ff3860" },
        },
        {
          name: "成交量", type: "bar", data: volumes, xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: { color: (p: any) => {
            const d = klineData[p.dataIndex]
            return d && d.close >= d.open ? "rgba(0,255,136,0.4)" : "rgba(255,56,96,0.4)"
          }},
        },
      ],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 60, end: 100 }],
    }
  }, [klineData])

  // Build report content map from analysts + direct fields
  const reportContent: Record<string, string> = {}
  if (detail.summary) reportContent["summary"] = detail.summary
  if (detail.analysts) {
    for (const [key, val] of Object.entries(detail.analysts)) {
      reportContent[key] = typeof val === "string" ? val : JSON.stringify(val, null, 2)
    }
  }

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

      {/* K-line chart */}
      <Card>
        <CardHeader><CardTitle className="text-sm">K 线走势（近 3 个月）</CardTitle></CardHeader>
        <CardContent>
          <ChartPanel option={klineOption} height={380} loading={klineData.length === 0} />
        </CardContent>
      </Card>

      {/* 7-tab report */}
      <Card>
        <CardContent className="pt-6">
          <Tabs defaultValue="summary">
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
