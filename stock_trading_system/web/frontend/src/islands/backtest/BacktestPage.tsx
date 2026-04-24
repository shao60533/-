import { useEffect, useState } from "react"
import { FlaskConical, Play, Clock } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiGet, apiPost } from "@/lib/api"

interface Strategy {
  id: string
  name: string
  description?: string
}

interface TaskSubmitResult {
  task_id: string
  status: string
}

export function BacktestPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [ticker, setTicker] = useState("")
  const [strategy, setStrategy] = useState("")
  const [startDate, setStartDate] = useState("2024-01-01")
  const [endDate, setEndDate] = useState(
    new Date().toISOString().slice(0, 10),
  )
  const [capital, setCapital] = useState("100000")
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<TaskSubmitResult | null>(
    null,
  )

  useEffect(() => {
    apiGet<Strategy[] | { strategies: Strategy[] }>("/api/backtest/strategies")
      .then((res) => {
        const list = Array.isArray(res)
          ? res
          : (res as { strategies: Strategy[] }).strategies ?? []
        setStrategies(list)
        if (list.length > 0) setStrategy(list[0].id)
      })
      .catch((err) =>
        setError(err.message ?? "Failed to load strategies"),
      )
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async () => {
    if (!ticker.trim() || !strategy) return
    setSubmitting(true)
    setError(null)
    setSubmitResult(null)
    try {
      const res = await apiPost<TaskSubmitResult>("/api/tasks/submit", {
        type: "backtest",
        params: {
          ticker: ticker.toUpperCase(),
          strategy,
          start_date: startDate,
          end_date: endDate,
          initial_capital: parseFloat(capital),
        },
      })
      setSubmitResult(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交失败")
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <FlaskConical className="h-5 w-5 text-[var(--color-accent-blue)]" />
        <h1 className="text-xl font-bold">策略回测</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>配置回测参数</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">股票代码</label>
              <Input
                placeholder="如 AAPL"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">策略</label>
              {strategies.length > 0 ? (
                <Select value={strategy} onValueChange={setStrategy}>
                  <SelectTrigger>
                    <SelectValue placeholder="选择策略" />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input disabled placeholder="无可用策略" />
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">开始日期</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">结束日期</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>

            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-sm text-muted-foreground">
                初始资金 (USD)
              </label>
              <Input
                type="number"
                min="1000"
                step="1000"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
              />
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-3">
            <Button
              onClick={handleSubmit}
              disabled={submitting || !ticker.trim() || !strategy}
              className="w-full sm:w-auto"
            >
              {submitting ? (
                <>
                  <Clock className="h-4 w-4 mr-1 animate-spin" />
                  提交中...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-1" />
                  开始回测
                </>
              )}
            </Button>

            {error && (
              <Alert variant="destructive">
                <AlertTitle>提交失败</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {submitResult && (
              <Alert variant="success">
                <AlertTitle>任务已提交</AlertTitle>
                <AlertDescription>
                  任务 ID:{" "}
                  <code className="font-mono">{submitResult.task_id}</code>
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
          </div>
        </CardContent>
      </Card>

      {strategies.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>可用策略</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="divide-y divide-border/50">
              {strategies.map((s) => (
                <div key={s.id} className="py-3 px-2">
                  <div className="font-semibold text-sm">{s.name}</div>
                  {s.description && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {s.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
