import { useState } from "react"
import { FileText, Send, Clock } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiPost } from "@/lib/api"

interface TaskSubmitResult {
  task_id: string
  status: string
  report?: ReportContent
}

interface ReportContent {
  title?: string
  content?: string
  generated_at?: string
  sections?: ReportSection[]
}

interface ReportSection {
  heading: string
  body: string
}

const REPORT_TYPES = [
  { value: "daily", label: "日报" },
  { value: "weekly", label: "周报" },
  { value: "monthly", label: "月报" },
  { value: "stock", label: "个股研报" },
] as const

export function ReportsPage() {
  const [reportType, setReportType] = useState<string>("daily")
  const [ticker, setTicker] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitResult, setSubmitResult] = useState<TaskSubmitResult | null>(
    null,
  )
  const [report, setReport] = useState<ReportContent | null>(null)

  const needsTicker = reportType === "stock"

  const handleSubmit = async () => {
    if (needsTicker && !ticker.trim()) return
    setSubmitting(true)
    setError(null)
    setSubmitResult(null)
    setReport(null)
    try {
      const params: Record<string, unknown> = { report_type: reportType }
      if (needsTicker) {
        params.ticker = ticker.toUpperCase()
      }
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "report",
        params,
      })
      setSubmitResult(res)
      if (res.report) {
        setReport(res.report)
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
          <CardTitle>生成报告</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
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

            {needsTicker && (
              <div className="flex-1 space-y-1.5">
                <label className="text-sm text-muted-foreground">
                  股票代码
                </label>
                <Input
                  placeholder="如 AAPL"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                />
              </div>
            )}

            <Button
              onClick={handleSubmit}
              disabled={submitting || (needsTicker && !ticker.trim())}
            >
              {submitting ? (
                <>
                  <Clock className="h-4 w-4 mr-1 animate-spin" />
                  生成中...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-1" />
                  生成报告
                </>
              )}
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="mt-4">
              <AlertTitle>生成失败</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {submitResult && !report && (
            <Alert variant="success" className="mt-4">
              <AlertTitle>任务已提交</AlertTitle>
              <AlertDescription>
                任务 ID:{" "}
                <code className="font-mono">{submitResult.task_id}</code>
                ，状态: {submitResult.status}。
                <a
                  href="/tasks"
                  className="ml-2 text-[var(--color-accent-blue)] hover:underline"
                >
                  查看任务进度
                </a>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {report && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>{report.title || "生成报告"}</CardTitle>
              {report.generated_at && (
                <Badge variant="muted">
                  {report.generated_at.slice(0, 19).replace("T", " ")}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {report.content && (
              <div className="prose prose-sm prose-invert max-w-none">
                <div className="whitespace-pre-wrap text-sm text-[var(--color-text-secondary)] leading-relaxed">
                  {report.content}
                </div>
              </div>
            )}
            {report.sections?.map((section, idx) => (
              <div key={idx} className="mt-4">
                <h3 className="font-semibold text-sm mb-1">{section.heading}</h3>
                <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
                  {section.body}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
