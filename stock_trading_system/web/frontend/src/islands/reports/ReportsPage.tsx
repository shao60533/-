import { Suspense, lazy, useEffect, useRef, useState } from "react"
import { FileText, Send, Clock, ArrowLeft, Sparkles } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"
import { apiGet, apiPost } from "@/lib/api"

const MarkdownBody = lazy(() => import("@/components/shared/MarkdownBody"))

interface TaskSubmitResult {
  task_id: string
  status: string
}

interface ReportContent {
  type?: string
  content?: string
  generated_at?: string
}

interface TaskResultEnvelope {
  task: {
    id: string
    type: string
    status: "pending" | "running" | "success" | "failed" | "cancelled"
    error_message?: string | null
    progress_pct?: number
  }
  result: ReportContent
}

/**
 * v1.7 — only the three portfolio-scoped reports remain. Stock-level
 * deep dives route through ``/analysis`` (the analysis pipeline)
 * because they share storage, rendering, and provenance with the
 * full structured-card view; duplicating them as a "report" task
 * was the source of the dual-history confusion.
 */
const REPORT_TYPES = [
  { value: "daily", label: "日报" },
  { value: "weekly", label: "周报" },
  { value: "monthly", label: "月报" },
] as const

const REPORT_LABEL: Record<string, string> = {
  daily: "日报", weekly: "周报", monthly: "月报",
}

function getReportIdFromUrl(): string | null {
  // ``?id=<task_id>`` query — submitted task_id replaces the URL on
  // submission so a refresh / share-link lands directly on the result.
  const q = new URLSearchParams(window.location.search).get("id")
  return q || null
}

export function ReportsPage() {
  const [reportId, setReportId] = useState<string | null>(getReportIdFromUrl)

  if (reportId) {
    return <ReportDetail reportId={reportId} onBack={() => {
      window.history.replaceState(null, "", "/reports")
      setReportId(null)
    }} />
  }
  return <ReportForm onSubmitted={(taskId) => {
    window.history.replaceState(null, "", `/reports?id=${taskId}`)
    setReportId(taskId)
  }} />
}

/* ── Form ─────────────────────────────────────────────────────── */

function ReportForm({ onSubmitted }: { onSubmitted: (taskId: string) => void }) {
  const [reportType, setReportType] = useState<string>("daily")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      // v1.7 — canonical field is ``type``. The earlier frontend sent
      // ``report_type`` while the worker read ``type``, which silently
      // defaulted weekly/monthly to daily. Backend tolerates both for
      // one release.
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "report",
        params: { type: reportType },
      })
      if (res.task_id) {
        onSubmitted(res.task_id)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <FileText className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">报告生成</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>生成持仓报告</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 form-row-mobile sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <label className="text-sm text-muted-foreground">报告类型</label>
              <Select value={reportType} onValueChange={setReportType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {REPORT_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button onClick={handleSubmit} disabled={submitting}>
              {submitting ? (
                <><Clock className="h-4 w-4 mr-1 animate-spin" />生成中...</>
              ) : (
                <><Send className="h-4 w-4 mr-1" />生成报告</>
              )}
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>生成失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <Alert className="mt-4">
            <AlertTitle className="text-xs flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              个股研报
            </AlertTitle>
            <AlertDescription className="text-xs">
              个股深度研报已并入 AI 分析主链路。请到{" "}
              <a className="text-[var(--color-accent-blue)] hover:underline" href="/analysis">
                /analysis
              </a>
              {" "}发起分析（结构化卡片 + 完整论述 + 收藏 / 导出 / 分享）。
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Detail (loads task result by task_id) ────────────────────── */

function ReportDetail({ reportId, onBack }: { reportId: string; onBack: () => void }) {
  const [envelope, setEnvelope] = useState<TaskResultEnvelope | null>(null)
  const [status, setStatus] = useState<string>("loading")
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false

    async function tick() {
      try {
        // Result endpoint returns 404 with ``{status, message}`` while
        // the task is still running — read both status codes the same
        // way (the apiGet wrapper rejects on 404, so fall back to the
        // task envelope to surface progress).
        const res = await apiGet<TaskResultEnvelope>(`/api/tasks/${reportId}/result`)
        if (cancelled) return
        setEnvelope(res)
        setStatus(res.task.status)
        return  // terminal — no more polls
      } catch {
        // Result not ready: peek at /api/tasks/<id> for status.
      }
      try {
        const t = await apiGet<{ status: string; error_message?: string }>(`/api/tasks/${reportId}`)
        if (cancelled) return
        setStatus(t.status)
        if (t.status === "failed" || t.status === "cancelled") {
          setError(t.error_message || `任务${t.status === "failed" ? "失败" : "已取消"}`)
          return
        }
        // Pending / running — poll again.
        pollRef.current = window.setTimeout(tick, 2000)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "加载失败")
      }
    }
    tick()
    return () => {
      cancelled = true
      if (pollRef.current) window.clearTimeout(pollRef.current)
    }
  }, [reportId])

  const result = envelope?.result
  const reportType = result?.type ?? envelope?.task?.type
  const generatedAt = result?.generated_at ?? null

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4 mr-1" />返回
        </Button>
        <h1 className="text-xl font-bold">报告</h1>
        {reportType && (
          <Badge variant="outline">
            {REPORT_LABEL[reportType] ?? reportType}
          </Badge>
        )}
        <Badge variant="muted" className="text-[10px] font-mono">{reportId}</Badge>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>无法加载报告</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error && !result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Clock className="h-4 w-4 animate-spin" />
              {status === "running" ? "生成中…" :
               status === "pending" ? "排队中…" : "加载中…"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </CardContent>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>
                {REPORT_LABEL[result.type ?? ""] ?? "持仓报告"}
              </CardTitle>
              {generatedAt && (
                <Badge variant="muted">
                  {generatedAt.slice(0, 19).replace("T", " ")}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {result.content && (
              <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                <MarkdownBody className="prose prose-sm prose-invert max-w-none text-[var(--color-text-secondary)]">
                  {result.content}
                </MarkdownBody>
              </Suspense>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
