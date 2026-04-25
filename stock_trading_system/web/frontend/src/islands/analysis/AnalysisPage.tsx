import { useEffect, useState } from "react"
import { Sparkles, Send, ArrowLeft, Clock } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { apiGet, apiPost } from "@/lib/api"

interface AnalysisDetail {
  id: string
  ticker: string
  signal: string
  date: string
  summary?: string
  confidence?: number
  analysts?: Record<string, unknown>
  recommendation?: string
  risk_level?: string
  created_at?: string
}

interface TaskSubmitResult {
  task_id: string
  status: string
}

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

export function AnalysisPage() {
  const [detailId] = useState<string | null>(getIdFromUrl)
  const [detail, setDetail] = useState<AnalysisDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [ticker, setTicker] = useState("")
  const [date, setDate] = useState(
    new Date().toISOString().slice(0, 10),
  )
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<TaskSubmitResult | null>(
    null,
  )

  useEffect(() => {
    if (!detailId) return
    setLoading(true)
    setError(null)
    apiGet<AnalysisDetail>(`/api/history/${detailId}`)
      .then((res) => setDetail(res))
      .catch((err) =>
        setError(err.message ?? "Failed to load analysis detail"),
      )
      .finally(() => setLoading(false))
  }, [detailId])

  const handleSubmit = async () => {
    if (!ticker.trim()) return
    setSubmitting(true)
    setError(null)
    setSubmitResult(null)
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "analysis",
        params: { ticker: ticker.toUpperCase(), date },
      })
      setSubmitResult(res)
      // Redirect to task center so user can track progress
      if (res.task_id) {
        setTimeout(() => {
          window.location.href = `/tasks`
        }, 800)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally {
      setSubmitting(false)
    }
  }

  if (detailId && loading) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (detailId && error) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Alert variant="destructive">
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => (window.location.href = "/analysis")}>
          <ArrowLeft className="h-4 w-4 mr-1" />
          返回
        </Button>
      </div>
    )
  }

  if (detailId && detail) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => (window.location.href = "/analysis")}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-xl font-bold font-mono">{detail.ticker}</h1>
          <Badge variant={signalVariant(detail.signal)}>
            {detail.signal || "N/A"}
          </Badge>
          {detail.confidence != null && (
            <span className="text-sm text-muted-foreground">
              置信度 {(detail.confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                分析日期
              </CardTitle>
            </CardHeader>
            <CardContent className="text-lg font-mono">
              {detail.date}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                信号
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Badge variant={signalVariant(detail.signal)} className="text-sm">
                {detail.signal || "N/A"}
              </Badge>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                风险等级
              </CardTitle>
            </CardHeader>
            <CardContent className="text-lg">
              {detail.risk_level || "-"}
            </CardContent>
          </Card>
        </div>

        {detail.summary && (
          <Card>
            <CardHeader>
              <CardTitle>分析摘要</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
                {detail.summary}
              </p>
            </CardContent>
          </Card>
        )}

        {detail.recommendation && (
          <Card>
            <CardHeader>
              <CardTitle>投资建议</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
                {detail.recommendation}
              </p>
            </CardContent>
          </Card>
        )}

        {detail.analysts && Object.keys(detail.analysts).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>分析师详情</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs bg-[var(--color-bg-secondary)] rounded p-3 overflow-x-auto max-h-80">
                {JSON.stringify(detail.analysts, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Sparkles className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">AI 分析</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>发起分析</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <label className="text-sm text-muted-foreground">股票代码</label>
              <Input
                placeholder="如 AAPL, TSLA"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
              />
            </div>
            <div className="w-full sm:w-44 space-y-1.5">
              <label className="text-sm text-muted-foreground">分析日期</label>
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <Button onClick={handleSubmit} disabled={submitting || !ticker.trim()}>
              {submitting ? (
                <>
                  <Clock className="h-4 w-4 mr-1 animate-spin" />
                  提交中...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-1" />
                  开始分析
                </>
              )}
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>提交失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {submitResult && (
            <Alert variant="success" className="mt-4">
              <AlertTitle>任务已提交</AlertTitle>
              <AlertDescription>
                任务 ID: <code className="font-mono">{submitResult.task_id}</code>
                ，状态: {submitResult.status}。
                <a
                  href="/app/tasks"
                  className="ml-2 text-[var(--color-accent-blue)] hover:underline"
                >
                  查看任务进度
                </a>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
